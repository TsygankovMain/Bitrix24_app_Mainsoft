import json
import time
import logging
from datetime import datetime, date, timedelta
from typing import List, Dict, Any, Optional, Union, Tuple

from b24pysdk import Client
from b24pysdk.bitrix_api.requests import BitrixAPIRequest
from django.core.cache import cache
from django.core.management import call_command
from django.db import connection
from django.db import transaction
from django.db.models import Max, Sum, Case, When, Value, FloatField, F
from django.utils import timezone

from .models import TimesheetItem, Bitrix24Account, ProjectCard
from .configuration_service import ConfigurationService

logger = logging.getLogger(__name__)

PROJECT_STAGE_NEW = "Новый"
PROJECT_STAGE_ESTIMATE = "В просчете"
PROJECT_STAGE_IN_WORK = "В работе"
PROJECT_STAGE_NO_WRITEOFF_30 = "Нет списаний 1 месяц"
PROJECT_STAGE_NO_WRITEOFF_90 = "Нет списаний 3 месяца"
PROJECT_STAGE_SUCCESS = "Успех"
PROJECT_STAGE_FAILED = "Провал"

PROJECT_MANUAL_STAGES = [
    PROJECT_STAGE_NEW,
    PROJECT_STAGE_ESTIMATE,
    PROJECT_STAGE_IN_WORK,
    PROJECT_STAGE_SUCCESS,
    PROJECT_STAGE_FAILED,
]

PROJECT_AUTO_STAGES = [
    PROJECT_STAGE_NO_WRITEOFF_30,
    PROJECT_STAGE_NO_WRITEOFF_90,
]

PROJECT_STAGE_ORDER = [
    PROJECT_STAGE_NEW,
    PROJECT_STAGE_ESTIMATE,
    PROJECT_STAGE_IN_WORK,
    PROJECT_STAGE_NO_WRITEOFF_30,
    PROJECT_STAGE_NO_WRITEOFF_90,
    PROJECT_STAGE_SUCCESS,
    PROJECT_STAGE_FAILED,
]

PROJECT_CARD_TABLE_NAME = ProjectCard._meta.db_table
BITRIX_REFERENCE_CACHE_TTL = 60 * 30
PROJECT_BOARD_CACHE_TTL = 60 * 2
HOMEPAGE_CACHE_TTL = 60 * 2
FILTER_EMPLOYEES_CACHE_SUFFIX = "filter-employees-v2"


def build_account_cache_key(account: Bitrix24Account, suffix: str) -> str:
    return f"mainsoft:v2:{account.pk}:{suffix}"


def invalidate_account_cache(account: Bitrix24Account, suffixes: List[str]) -> None:
    for suffix in suffixes:
        try:
            cache.delete(build_account_cache_key(account, suffix))
        except Exception as exc:
            logger.warning("Cache delete failed for %s: %s", suffix, exc)


def invalidate_project_runtime_caches(account: Bitrix24Account) -> None:
    invalidate_account_cache(account, [
        "filter-employees",
        FILTER_EMPLOYEES_CACHE_SUFFIX,
        "filter-projects",
        "project-board",
        "project-board-meta",
        "project-board-companies",
        "project-board-homepage",
    ])


def ensure_project_card_schema() -> bool:
    try:
        if PROJECT_CARD_TABLE_NAME in connection.introspection.table_names():
            return True
    except Exception as exc:
        logger.warning("ProjectCard schema check failed: %s", exc)

    try:
        call_command("migrate", interactive=False, verbosity=0)
    except Exception as exc:
        logger.warning("ProjectCard auto-migrate failed: %s", exc)

    try:
        return PROJECT_CARD_TABLE_NAME in connection.introspection.table_names()
    except Exception as exc:
        logger.warning("ProjectCard schema re-check failed: %s", exc)
        return False


def get_project_card_queryset(account: Bitrix24Account):
    if not ensure_project_card_schema():
        return ProjectCard.objects.none()

    return ProjectCard.objects.filter(bitrix24_account=account)


def build_local_project_groups(account: Bitrix24Account) -> List[Dict[str, Any]]:
    rows = (
        TimesheetItem.objects.filter(bitrix24_account=account)
        .exclude(project_id__isnull=True)
        .exclude(project_id="")
        .values("project_id", "project_title")
        .distinct()
    )

    items: List[Dict[str, Any]] = []
    seen_ids = set()

    for row in rows:
        project_id = str(row.get("project_id") or "").strip()
        project_name = str(row.get("project_title") or "").strip() or f"Проект {project_id}"

        if not project_id or project_id in seen_ids:
            continue

        seen_ids.add(project_id)
        items.append({
            "ID": project_id,
            "NAME": project_name,
            "PROJECT": "Y",
            "CLOSED": "N",
        })

    return items

# Field Constants from Documentation
class BitrixDataService:
    """Service for fetching data from Bitrix24"""

    def __init__(self, client: Client, config: Dict[str, Any], account: Optional[Bitrix24Account] = None):
        self.client = client
        self.config = config
        self.account = account
        self.entity_type_id = config.get('sp_entity_type_id', 0)

    def check_connection(self):
        """Diagnostic: List all SPAs to verify access and IDs"""
        try:
            # crm.type.list via token directly
            response = self.client._bitrix_token.call_method("crm.type.list", {})
            types = response.get('result', {}).get('types', [])
            logger.info(f"Found {len(types)} Smart Processes:")
            for t in types:
                logger.info(f"SPA: {t.get('title')} (ID: {t.get('entityTypeId')})")
            
            # Check for configured ID specifically
            target = next((t for t in types if str(t.get('entityTypeId')) == str(self.entity_type_id)), None)
            if target:
                logger.info(f"Target SPA {self.entity_type_id} FOUND.")
            else:
                logger.error(f"Target SPA {self.entity_type_id} NOT FOUND in crm.type.list!")
        except Exception as e:
            logger.error(f"Failed to list SPAs: {e}")

    def fetch_users(self, user_ids: List[str]) -> Dict[str, str]:
        """
        Fetches users by ID and returns a map {id: "Last First"}.
        Handles Bitrix24 employee field quirk: values can be stored as "[12]" (stringified list).
        Builds a dual-key map so BOTH "12" and "[12]" formats resolve to the name.
        """
        if not user_ids:
            return {}

        # --- Normalize IDs ---
        # Bitrix24 employee fields return lists: [12]. After str() they become "[12]".
        # We need to extract the actual numeric ID and remember the original key.
        numeric_to_original: Dict[str, str] = {}  # {"12": "[12]"}  or  {"12": "12"}
        for uid in user_ids:
            if not uid:
                continue
            uid_str = str(uid).strip()
            # Pattern "[12]" or "[12, 15]" — take the first element
            if uid_str.startswith('['):
                try:
                    import json as _json
                    parsed = _json.loads(uid_str)
                    if isinstance(parsed, list) and parsed:
                        numeric = str(parsed[0])
                        numeric_to_original[numeric] = uid_str
                        continue
                except Exception:
                    pass  # Not a valid JSON list — skip
                continue  # Unrecognisable "[...]" format — skip it
            # Normal numeric string
            if uid_str and uid_str.lstrip('-').isdigit():
                numeric_to_original[uid_str] = uid_str
            # else: skip garbage strings

        if not numeric_to_original:
            return {}

        try:
            response = self.client._bitrix_token.call_method(
                "user.get",
                {"FILTER": {"ID": list(numeric_to_original.keys())}}
            )
            users = response.get('result', [])
            user_map: Dict[str, str] = {}
            for u in users:
                numeric_id = str(u.get('ID', ''))
                name = f"{u.get('LAST_NAME', '')} {u.get('NAME', '')}".strip()
                if not name:
                    name = u.get('EMAIL') or f"User {numeric_id}"
                # Key by numeric ID (for new data: "12")
                user_map[numeric_id] = name
                # Also key by original format (for old data in DB: "[12]")
                original = numeric_to_original.get(numeric_id)
                if original and original != numeric_id:
                    user_map[original] = name
            return user_map
        except Exception as e:
            logger.error(f"Error fetching users: {e}")
            return {}

    def fetch_active_users(self) -> List[Dict[str, str]]:
        """Fetch all active Bitrix24 users for report filters."""
        if self.account:
            cache_key = build_account_cache_key(self.account, FILTER_EMPLOYEES_CACHE_SUFFIX)
            cached = cache.get(cache_key)
            if cached:
                return cached
            if cached == []:
                cache.delete(cache_key)

        try:
            response = self.client._bitrix_token.call_method(
                "user.get",
                {
                    "FILTER": {"ACTIVE": "Y"},
                    "sort": "LAST_NAME",
                    "order": "ASC",
                }
            )
            users = response.get('result', [])
            result: List[Dict[str, str]] = []

            for user in users:
                user_id = str(user.get('ID', '')).strip()
                if not user_id:
                    continue

                user_type = str(user.get('USER_TYPE', '')).strip().lower()
                if user_type and user_type != 'employee':
                    continue

                name = f"{user.get('LAST_NAME', '')} {user.get('NAME', '')}".strip()
                if not name:
                    name = user.get('EMAIL') or f"User {user_id}"

                result.append({
                    "id": user_id,
                    "name": name,
                })

            result = sorted(result, key=lambda item: item["name"])
            if self.account:
                cache_key = build_account_cache_key(self.account, FILTER_EMPLOYEES_CACHE_SUFFIX)
                if result:
                    cache.set(cache_key, result, BITRIX_REFERENCE_CACHE_TTL)
                else:
                    cache.delete(cache_key)
            return result
        except Exception as e:
            logger.error(f"Error fetching active users: {e}")
            return []

    def fetch_all_items(self, extra_filter: Optional[Dict] = None) -> List[Dict[str, Any]]:
        """
        Fetches items from Smart Process
        """
        self.check_connection()
        
        if not self.entity_type_id:
             logger.error("No SP Entity Type ID configured")
             return []

        base_filter = {"entityTypeId": self.entity_type_id}
        if extra_filter:
            base_filter.update(extra_filter)

        # DEBUG: Select ALL fields to see what we actually get
        select = ["*", "UF_*"]

        logger.info(f"Executing single request fetch (SELECT *, UF_*) for SPA {self.entity_type_id}")
        
        try:
            response = self.client._bitrix_token.call_method(
                "crm.item.list",
                {
                    "entityTypeId": self.entity_type_id,
                    "filter": base_filter,
                    "select": select,
                    "order": {"id": "DESC"},
                    "start": 0,
                    "limit": 50
                }
            )
            
            result = response.get('result', {})
            all_items = result.get('items', [])
            
        except Exception as e:
            logger.error(f"Error fetching items: {e}")
            all_items = []

        logger.info(f"Total items fetched from Bitrix24: {len(all_items)}")
        if all_items:
            logger.info("First item FULL DUMP:")
            logger.info(json.dumps(all_items[0], indent=2, default=str))
        
        return all_items


class DataProcessingService:
    """Service for normalizing and processing raw Bitrix24 data"""

    def __init__(self, mapping: Dict[str, str]):
        self.mapping = mapping

    def normalize_items(self, raw_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        normalized = []
        dropped_count = 0
        
        # Helper to get field code from mapping
        def get_f(key):
            return self.mapping.get(key)

        field_task_id = get_f('id_zadachi')
        field_task_hierarchy = get_f('id_zadach_ierarhiya')
        field_title_hierarchy = get_f('title_zadach_ierarhiya')
        field_project_name = get_f('project_title')
        field_project_id = get_f('project_id')
        field_is_billable = get_f('uchitivaem')
        field_hours = get_f('kolichestvo_chasov')
        field_non_billable = get_f('ne_uchitivaemie_chasi')
        field_desc = get_f('opisanie')
        field_employee = get_f('sotrudnik')
        field_date = get_f('data')
        
        for item in raw_items:
            # 1. Validation: Task ID is required
            if not field_task_id or not item.get(field_task_id):
                dropped_count += 1
                if dropped_count <= 5: 
                    # logger.warning(f"Dropping item {item.get('id')} because task_id ({field_task_id}) is missing.")
                    pass
                continue

            # 2. Parse Hierarchy
            try:
                task_hierarchy = self._parse_json_list(item.get(field_task_hierarchy))
                title_hierarchy = self._parse_json_list(item.get(field_title_hierarchy))
            except Exception:
                continue

            # 3. Determine Project
            project_name = item.get(field_project_name)
            if not project_name:
                if title_hierarchy and len(title_hierarchy) > 0:
                    project_name = title_hierarchy[0]
                else:
                    project_name = "Не определён"

            # 4. Task Name
            task_name = title_hierarchy[-1] if title_hierarchy else "Без названия"

            # 5. Billable status
            is_billable_raw = item.get(field_is_billable)
            is_billable = str(is_billable_raw).upper() in ['Y', '1', 'TRUE']

            hours = float(item.get(field_hours) or 0)
            non_billable = float(item.get(field_non_billable) or 0)

            # Employee field in Bitrix24 CRM returns a LIST even for single-select: [12] or [12, 15]
            # str([12]) would produce "[12]" which is NOT a valid user ID for user.get
            emp_raw = item.get(field_employee)
            if isinstance(emp_raw, list):
                emp_id = str(emp_raw[0]) if emp_raw else ""
            elif emp_raw is not None:
                emp_id = str(emp_raw).strip()
            else:
                emp_id = ""

            normalized_item = {
                "id_elem": str(item.get('id')),
                "id_zadachi": str(item.get(field_task_id)),
                "sotrudnik_id": emp_id,
                "kolichestvo_chasov": hours,
                "uchitivaem": is_billable,
                "ne_uchitivaemie_chasi": non_billable,
                "opisanie": item.get(field_desc) or "",
                "id_zadach_ierarhiya": task_hierarchy,
                "title_zadach_ierarhiya": title_hierarchy,
                "nazvanie_zadachi": task_name,
                "project_name": project_name,
                "project_id": str(item.get(field_project_id) or ""),
                "data": item.get(field_date) or item.get("createdTime"),
                "source_created_at": item.get("createdTime")
            }
            normalized.append(normalized_item)
        
        logger.info(f"Normalization complete. Input: {len(raw_items)}, Output: {len(normalized)}, Dropped: {dropped_count}")
        return normalized

    def _parse_json_list(self, json_str: Any) -> List[str]:
        if not json_str:
            return []
        if isinstance(json_str, list):
            return [str(x) for x in json_str]
        try:
            parsed = json.loads(json_str)
            if isinstance(parsed, list):
                return [str(x) for x in parsed]
            return []
        except json.JSONDecodeError:
            return []


class ReportService:
    """Service for Aggregating Reports"""

    def generate_employee_projects(self, items: List[Dict[str, Any]], user_map: Dict[str, str] = None) -> List[Dict[str, Any]]:
        """
        Group by Employee -> Project -> Task Hierarchy -> Items
        Returns a recursive tree structure.
        """
        tree = {}
        user_map = user_map or {}

        for item in items:
            emp_id = item['sotrudnik_id']
            proj_name = item['project_name'] or "Без проекта"
            
            # Hours logic
            hours = item['kolichestvo_chasov']
            is_billable = item.get('uchitivaem', False)
            billable = hours if is_billable else 0.0
            non_billable = hours if not is_billable else 0.0

            # 1. Employee Node
            if emp_id not in tree:
                tree[emp_id] = {
                    "type": "employee",
                    "id": emp_id,
                    "name": user_map.get(emp_id, f"Сотрудник {emp_id}"),
                    "total_hours": 0.0,
                    "billable_hours": 0.0,
                    "non_billable_hours": 0.0,
                    "children": {} # Keyed by project name
                }
            
            emp_node = tree[emp_id]
            emp_node["total_hours"] += hours
            emp_node["billable_hours"] += billable
            emp_node["non_billable_hours"] += non_billable
            
            # 2. Project Node
            if proj_name not in emp_node["children"]:
                emp_node["children"][proj_name] = {
                    "type": "project",
                    "name": proj_name,
                    "total_hours": 0.0,
                    "billable_hours": 0.0,
                    "non_billable_hours": 0.0,
                    "children": {} # Keyed by task ID of the root task
                }
            
            proj_node = emp_node["children"][proj_name]
            proj_node["total_hours"] += hours
            proj_node["billable_hours"] += billable
            proj_node["non_billable_hours"] += non_billable
            
            # 3. Task Hierarchy
            t_ids = item.get('id_zadach_ierarhiya') or []
            t_titles = item.get('title_zadach_ierarhiya') or []
            
            current_level_children = proj_node["children"]
            
            if not t_ids:
                 t_ids = ["unknown"]
                 t_titles = ["Без задачи"]

            for idx, t_id in enumerate(t_ids):
                t_title = t_titles[idx] if idx < len(t_titles) else f"Task {t_id}"
                
                if t_id not in current_level_children:
                    current_level_children[t_id] = {
                        "type": "task",
                        "id": t_id,
                        "name": t_title,
                        "total_hours": 0.0,
                        "billable_hours": 0.0,
                        "non_billable_hours": 0.0,
                        "children": {}, 
                        "items": []     
                    }
                
                task_node = current_level_children[t_id]
                task_node["total_hours"] += hours
                task_node["billable_hours"] += billable
                task_node["non_billable_hours"] += non_billable
                
                if idx == len(t_ids) - 1:
                    task_node["items"].append(item)
                else:
                    current_level_children = task_node["children"]

        return self._convert_tree_to_list(tree)

    def _convert_tree_to_list(self, nodes_dict: Dict) -> List[Dict]:
        result = []
        for key, node in nodes_dict.items():
            # Recursively convert children if present
            if "children" in node:
                node["children"] = self._convert_tree_to_list(node["children"])
            
            # Sort children? (Optional, maybe by name)
            
            result.append(node)
        return result

    def _get_employee_name(self, emp_id: str) -> str:
        # Placeholder. In real app we might want to fetch users or use a cache.
        return f"Employee {emp_id}"

    def generate_project_employees(self, items: List[Dict[str, Any]], user_map: Dict[str, str] = None) -> List[Dict[str, Any]]:
        """
        Group by Project -> Employee -> Task Hierarchy -> Items
        Returns a recursive tree structure.
        """
        tree = {}
        user_map = user_map or {}

        for item in items:
            emp_id = item['sotrudnik_id']
            proj_name = item['project_name'] or "Без проекта"
            
            # Hours logic
            hours = item['kolichestvo_chasov']
            is_billable = item.get('uchitivaem', False)
            billable = hours if is_billable else 0.0
            non_billable = hours if not is_billable else 0.0
            
            # 1. Project Node
            if proj_name not in tree:
                tree[proj_name] = {
                    "type": "project",
                    "id": proj_name, # Use name as ID for project grouping
                    "name": proj_name,
                    "total_hours": 0.0,
                    "billable_hours": 0.0,
                    "non_billable_hours": 0.0,
                    "children": {} # Keyed by employee ID
                }
            
            proj_node = tree[proj_name]
            proj_node["total_hours"] += hours
            proj_node["billable_hours"] += billable
            proj_node["non_billable_hours"] += non_billable
            
            # 2. Employee Node
            if emp_id not in proj_node["children"]:
                proj_node["children"][emp_id] = {
                    "type": "employee",
                    "id": emp_id,
                    "name": user_map.get(emp_id, f"Сотрудник {emp_id}"),
                    "total_hours": 0.0,
                    "billable_hours": 0.0,
                    "non_billable_hours": 0.0,
                    "children": {} # Keyed by task ID
                }
            
            emp_node = proj_node["children"][emp_id]
            emp_node["total_hours"] += hours
            emp_node["billable_hours"] += billable
            emp_node["non_billable_hours"] += non_billable

            # 3. Task Hierarchy
            t_ids = item.get('id_zadach_ierarhiya') or []
            t_titles = item.get('title_zadach_ierarhiya') or []
            
            current_level_children = emp_node["children"]
            
            if not t_ids:
                 t_ids = ["unknown"]
                 t_titles = ["Без задачи"]

            for idx, t_id in enumerate(t_ids):
                t_title = t_titles[idx] if idx < len(t_titles) else f"Task {t_id}"
                
                if t_id not in current_level_children:
                    current_level_children[t_id] = {
                        "type": "task",
                        "id": t_id,
                        "name": t_title,
                        "total_hours": 0.0,
                        "billable_hours": 0.0,
                        "non_billable_hours": 0.0,
                        "children": {}, 
                        "items": []     
                    }
                
                task_node = current_level_children[t_id]
                task_node["total_hours"] += hours
                task_node["billable_hours"] += billable
                task_node["non_billable_hours"] += non_billable
                
                if idx == len(t_ids) - 1:
                    task_node["items"].append(item)
                else:
                    current_level_children = task_node["children"]

        return self._convert_tree_to_list(tree)

    def generate_project_task_employees(self, items: List[Dict[str, Any]], user_map: Dict[str, str] = None) -> List[Dict[str, Any]]:
        """
        Group by Project -> Task Hierarchy -> Employee -> Items
        For the new "Учет по проектам/задачам" report.
        """
        tree = {}
        user_map = user_map or {}

        for item in items:
            emp_id = item['sotrudnik_id']
            proj_name = item['project_name'] or "Без проекта"
            
            # Hours logic
            hours = item['kolichestvo_chasov']
            is_billable = item.get('uchitivaem', False)
            billable = hours if is_billable else 0.0
            non_billable = hours if not is_billable else 0.0
            
            # 1. Project Node
            if proj_name not in tree:
                tree[proj_name] = {
                    "type": "project",
                    "id": proj_name,
                    "name": proj_name,
                    "total_hours": 0.0,
                    "billable_hours": 0.0,
                    "non_billable_hours": 0.0,
                    "children": {}
                }
            
            proj_node = tree[proj_name]
            proj_node["total_hours"] += hours
            proj_node["billable_hours"] += billable
            proj_node["non_billable_hours"] += non_billable
            
            # 2. Task Hierarchy
            t_ids = item.get('id_zadach_ierarhiya') or []
            t_titles = item.get('title_zadach_ierarhiya') or []
            
            current_level_children = proj_node["children"]
            
            if not t_ids:
                t_ids = ["unknown"]
                t_titles = ["Без задачи"]

            for idx, t_id in enumerate(t_ids):
                t_title = t_titles[idx] if idx < len(t_titles) else f"Task {t_id}"
                
                if t_id not in current_level_children:
                    current_level_children[t_id] = {
                        "type": "task",
                        "id": t_id,
                        "name": t_title,
                        "total_hours": 0.0,
                        "billable_hours": 0.0,
                        "non_billable_hours": 0.0,
                        "children": {},
                        "employees": {}
                    }
                
                task_node = current_level_children[t_id]
                task_node["total_hours"] += hours
                task_node["billable_hours"] += billable
                task_node["non_billable_hours"] += non_billable
                
                if idx == len(t_ids) - 1:
                    # Leaf task — add employee grouping
                    if emp_id not in task_node["employees"]:
                        task_node["employees"][emp_id] = {
                            "type": "employee",
                            "id": emp_id,
                            "name": user_map.get(emp_id, f"Сотрудник {emp_id}"),
                            "total_hours": 0.0,
                            "billable_hours": 0.0,
                            "non_billable_hours": 0.0,
                            "items": []
                        }
                    
                    emp_node = task_node["employees"][emp_id]
                    emp_node["total_hours"] += hours
                    emp_node["billable_hours"] += billable
                    emp_node["non_billable_hours"] += non_billable
                    emp_node["items"].append(item)
                else:
                    current_level_children = task_node["children"]

        return self._convert_pte_tree(tree)

    def _convert_pte_tree(self, nodes_dict: Dict) -> List[Dict]:
        """Convert project-task-employee tree to list, handling employees dict."""
        result = []
        for key, node in nodes_dict.items():
            if "children" in node:
                node["children"] = self._convert_pte_tree(node["children"])
            if "employees" in node:
                node["employees"] = list(node["employees"].values())
            result.append(node)
        return result


        """
        Matrix: Employee vs Date (Day of month)
        Assumption: items are filtered by month before passing here, 
        or we handle all dates provided.
        """
        report = {}
        
        for item in items:
            emp_id = item['sotrudnik_id']
            hours = item['kolichestvo_chasov']
            date_str = item['data'] # ISO format usually
            
            if not date_str:
                continue
                
            # Parse date to get day
            try:
                # ISO format '2023-10-25T00:00:00+03:00'
                dt = datetime.fromisoformat(date_str)
                day_key = str(dt.day)
            except ValueError:
                continue
            
            if emp_id not in report:
                report[emp_id] = {"employee_id": emp_id, "total": 0.0, "days": {}}
            
            report[emp_id]["total"] += hours
            if day_key not in report[emp_id]["days"]:
                report[emp_id]["days"][day_key] = 0.0
            report[emp_id]["days"][day_key] += hours


        return list(report.values())


    def generate_daily_workload(self, items: List[Dict[str, Any]], user_map: Dict[str, str], date_from: str, date_to: str) -> Dict[str, Any]:
        """
        Generates data for Daily Workload Report (Matrix View).
        """
        from datetime import datetime, timedelta, date

        # 1. Parse dates and generate range
        try:
            start_date = date.fromisoformat(date_from)
            end_date = date.fromisoformat(date_to)
        except (ValueError, TypeError):
            # Fallback to current month if invalid
            today = date.today()
            start_date = date(today.year, today.month, 1)
            end_date = today

        # Generate list of days for header
        header_days = []
        curr = start_date
        while curr <= end_date:
            header_days.append({
                "date": curr.isoformat(),
                "day": curr.day,
                "weekday": curr.weekday(), # 0=Mon, 5=Sat, 6=Sun
                "is_weekend": curr.weekday() >= 5
            })
            curr += timedelta(days=1)

        # 2. Aggregate Data
        # Structure: { emp_id: { name: "", days: { "2023-10-01": { total: 0, items: [] } } } }
        agg = {}
        
        for item in items:
            emp_id = item['sotrudnik_id']
            date_str = item['data']
            if not date_str:
                continue
                
            # Normalize date to YYYY-MM-DD
            try:
                dt = datetime.fromisoformat(date_str).date()
                d_key = dt.isoformat()
            except ValueError:
                continue
            
            # Skip if out of range (though validation should handle this in view)
            if not (start_date <= dt <= end_date):
                continue

            if emp_id not in agg:
                agg[emp_id] = {
                    "id": emp_id,
                    "name": user_map.get(emp_id, f"User {emp_id}"),
                    "days": {}
                }
            
            if d_key not in agg[emp_id]["days"]:
                agg[emp_id]["days"][d_key] = {
                    "total": 0.0,
                    "items": []
                }
            
            hours = float(item['kolichestvo_chasov'] or 0)
            agg[emp_id]["days"][d_key]["total"] += hours
            agg[emp_id]["days"][d_key]["items"].append({
                "task_id": item['id_zadachi'],
                "task_title": item['nazvanie_zadachi'],
                "project_title": item['project_name'],
                "hours": hours,
                "description": item['opisanie']
            })

        # 3. Format Output Lines
        rows = []
        for emp_id, data in agg.items():
            row_days = {}
            for day_obj in header_days:
                d_key = day_obj["date"]
                day_data = data["days"].get(d_key, {"total": 0.0, "items": []})
                
                total = day_data["total"]
                # Color Logic
                # < 6: orange
                # 6-9: green
                # > 9: yellow
                if total == 0:
                    status = 'neutral' # Empty
                elif total < 6:
                    status = 'orange'
                elif total <= 9:
                    status = 'green'
                else:
                    status = 'yellow'
                
                row_days[d_key] = {
                    "total": round(total, 2),
                    "status": status,
                    "items": day_data["items"]
                }
            
            rows.append({
                "employee": {
                    "id": emp_id,
                    "name": data["name"]
                },
                "days": row_days
            })
        
        # Sort rows by employee name
        rows.sort(key=lambda x: x["employee"]["name"])

        return {
            "header_days": header_days,
            "rows": rows
        }

    def generate_revenue_leakage(self, items: List[Dict[str, Any]], user_map: Dict[str, str] = None) -> Dict[str, Any]:
        """Aggregates billable vs non-billable hours by project and employee."""
        user_map = user_map or {}
        project_map: Dict[str, Dict[str, Any]] = {}
        employee_totals: Dict[str, Dict[str, Any]] = {}

        total_hours = 0.0
        total_billable = 0.0
        total_non_billable = 0.0

        for item in items:
            emp_id = str(item.get('sotrudnik_id') or '')
            project_name = item.get('project_name') or "Без проекта"
            hours = float(item.get('kolichestvo_chasov') or 0)
            is_billable = bool(item.get('uchitivaem', False))
            billable_hours = hours if is_billable else 0.0
            non_billable_hours = 0.0 if is_billable else hours

            total_hours += hours
            total_billable += billable_hours
            total_non_billable += non_billable_hours

            if project_name not in project_map:
                project_map[project_name] = {
                    "name": project_name,
                    "total_hours": 0.0,
                    "billable_hours": 0.0,
                    "non_billable_hours": 0.0,
                    "employees": {}
                }

            project_row = project_map[project_name]
            project_row["total_hours"] += hours
            project_row["billable_hours"] += billable_hours
            project_row["non_billable_hours"] += non_billable_hours

            if emp_id not in project_row["employees"]:
                project_row["employees"][emp_id] = {
                    "employee_id": emp_id,
                    "employee_name": user_map.get(emp_id, f"Сотрудник {emp_id}" if emp_id else "Без сотрудника"),
                    "total_hours": 0.0,
                    "billable_hours": 0.0,
                    "non_billable_hours": 0.0,
                }

            employee_row = project_row["employees"][emp_id]
            employee_row["total_hours"] += hours
            employee_row["billable_hours"] += billable_hours
            employee_row["non_billable_hours"] += non_billable_hours

            if emp_id not in employee_totals:
                employee_totals[emp_id] = {
                    "total_hours": 0.0,
                    "non_billable_hours": 0.0,
                }

            employee_totals[emp_id]["total_hours"] += hours
            employee_totals[emp_id]["non_billable_hours"] += non_billable_hours

        project_rows = []
        risk_rows = []

        for project in project_map.values():
            project_total = project["total_hours"]
            project_loss_rate = (project["non_billable_hours"] / project_total * 100.0) if project_total else 0.0
            employees = []

            for employee in project["employees"].values():
                employee_total = employee["total_hours"]
                employee_loss_rate = (employee["non_billable_hours"] / employee_total * 100.0) if employee_total else 0.0
                employee["loss_rate"] = round(employee_loss_rate, 1)
                employees.append(employee)
                risk_rows.append({
                    "project_name": project["name"],
                    "employee_id": employee["employee_id"],
                    "employee_name": employee["employee_name"],
                    "total_hours": round(employee_total, 2),
                    "billable_hours": round(employee["billable_hours"], 2),
                    "non_billable_hours": round(employee["non_billable_hours"], 2),
                    "loss_rate": round(employee_loss_rate, 1)
                })

            employees.sort(key=lambda row: (row["non_billable_hours"], row["loss_rate"]), reverse=True)
            project_rows.append({
                "name": project["name"],
                "total_hours": round(project_total, 2),
                "billable_hours": round(project["billable_hours"], 2),
                "non_billable_hours": round(project["non_billable_hours"], 2),
                "loss_rate": round(project_loss_rate, 1),
                "employee_count": len(employees),
                "employees": employees
            })

        project_rows.sort(key=lambda row: (row["non_billable_hours"], row["loss_rate"]), reverse=True)
        risk_rows.sort(key=lambda row: (row["non_billable_hours"], row["loss_rate"]), reverse=True)

        high_risk_project_count = sum(1 for row in project_rows if row["loss_rate"] >= 30.0 and row["total_hours"] > 0)
        high_risk_employee_count = 0
        for employee in employee_totals.values():
            emp_total = employee["total_hours"]
            emp_loss_rate = (employee["non_billable_hours"] / emp_total * 100.0) if emp_total else 0.0
            if emp_loss_rate >= 30.0 and emp_total > 0:
                high_risk_employee_count += 1

        return {
            "summary": {
                "total_hours": round(total_hours, 2),
                "billable_hours": round(total_billable, 2),
                "non_billable_hours": round(total_non_billable, 2),
                "loss_rate": round((total_non_billable / total_hours * 100.0) if total_hours else 0.0, 1),
                "project_count": len(project_rows),
                "high_risk_project_count": high_risk_project_count,
                "high_risk_employee_count": high_risk_employee_count
            },
            "project_rows": project_rows,
            "risk_rows": risk_rows
        }

    def generate_time_entry_discipline(self, items: List[Dict[str, Any]], user_map: Dict[str, str] = None) -> Dict[str, Any]:
        """Measures delay between reflection date and actual Bitrix item creation time."""
        user_map = user_map or {}
        buckets = {
            "0": 0,
            "1": 0,
            "2": 0,
            "3": 0,
            "4+": 0,
        }
        employee_map: Dict[str, Dict[str, Any]] = {}

        total_entries = 0
        same_day_count = 0
        next_day_count = 0
        two_plus_count = 0
        total_lag_days = 0.0
        fallback_entries = 0

        for item in items:
            emp_id = str(item.get('sotrudnik_id') or '')
            reflection_dt = self._parse_datetime(item.get('date_reflection'))
            source_created_at = self._parse_datetime(item.get('source_created_at'))

            if source_created_at is None:
                source_created_at = self._parse_datetime(item.get('created_at'))
                if source_created_at is not None:
                    fallback_entries += 1

            if reflection_dt is None or source_created_at is None:
                continue

            lag_days = max((source_created_at.date() - reflection_dt.date()).days, 0)
            total_entries += 1
            total_lag_days += lag_days

            if lag_days == 0:
                same_day_count += 1
                buckets["0"] += 1
            elif lag_days == 1:
                next_day_count += 1
                buckets["1"] += 1
            elif lag_days == 2:
                two_plus_count += 1
                buckets["2"] += 1
            elif lag_days == 3:
                two_plus_count += 1
                buckets["3"] += 1
            else:
                two_plus_count += 1
                buckets["4+"] += 1

            if emp_id not in employee_map:
                employee_map[emp_id] = {
                    "employee_id": emp_id,
                    "employee_name": user_map.get(emp_id, f"Сотрудник {emp_id}" if emp_id else "Без сотрудника"),
                    "entry_count": 0,
                    "same_day_count": 0,
                    "late_entries": 0,
                    "total_lag_days": 0.0,
                    "max_lag_days": 0,
                    "last_late_entry_date": None,
                }

            employee = employee_map[emp_id]
            employee["entry_count"] += 1
            employee["total_lag_days"] += lag_days
            employee["max_lag_days"] = max(employee["max_lag_days"], lag_days)

            if lag_days == 0:
                employee["same_day_count"] += 1

            if lag_days >= 2:
                employee["late_entries"] += 1
                last_late_date = reflection_dt.date().isoformat()
                if employee["last_late_entry_date"] is None or last_late_date > employee["last_late_entry_date"]:
                    employee["last_late_entry_date"] = last_late_date

        employee_rows = []
        for employee in employee_map.values():
            entry_count = employee["entry_count"]
            same_day_share = (employee["same_day_count"] / entry_count) if entry_count else 0.0
            avg_lag_days = (employee["total_lag_days"] / entry_count) if entry_count else 0.0

            risk_level = "Низкий"
            if avg_lag_days >= 2.0 or employee["late_entries"] >= 5:
                risk_level = "Высокий"
            elif avg_lag_days >= 1.0 or employee["late_entries"] >= 2:
                risk_level = "Средний"

            employee_rows.append({
                "employee_id": employee["employee_id"],
                "employee_name": employee["employee_name"],
                "entry_count": entry_count,
                "same_day_share": round(same_day_share, 3),
                "avg_lag_days": round(avg_lag_days, 1),
                "late_entries": employee["late_entries"],
                "max_lag_days": employee["max_lag_days"],
                "last_late_entry_date": employee["last_late_entry_date"],
                "risk_level": risk_level
            })

        employee_rows.sort(key=lambda row: (row["avg_lag_days"], row["late_entries"], -row["same_day_share"]), reverse=True)

        lag_buckets = [
            {"label": "0д", "count": buckets["0"]},
            {"label": "1д", "count": buckets["1"]},
            {"label": "2д", "count": buckets["2"]},
            {"label": "3д", "count": buckets["3"]},
            {"label": "4+д", "count": buckets["4+"]},
        ]

        return {
            "summary": {
                "total_entries": total_entries,
                "same_day_share": round((same_day_count / total_entries) if total_entries else 0.0, 3),
                "next_day_share": round((next_day_count / total_entries) if total_entries else 0.0, 3),
                "two_plus_share": round((two_plus_count / total_entries) if total_entries else 0.0, 3),
                "avg_lag_days": round((total_lag_days / total_entries) if total_entries else 0.0, 1),
                "retro_entries": two_plus_count,
                "high_risk_employee_count": sum(1 for row in employee_rows if row["risk_level"] == "Высокий"),
                "fallback_entries": fallback_entries
            },
            "lag_buckets": lag_buckets,
            "employee_rows": employee_rows
        }

    def generate_focus_analysis(self, items: List[Dict[str, Any]], user_map: Dict[str, str] = None) -> Dict[str, Any]:
        """Shows how much employees are spread across projects and tasks."""
        user_map = user_map or {}
        employee_map: Dict[str, Dict[str, Any]] = {}

        total_hours = 0.0
        total_entries = 0

        for item in items:
            emp_id = str(item.get('sotrudnik_id') or '')
            project_name = item.get('project_name') or "Без проекта"
            task_id = str(item.get('id_zadachi') or item.get('task_id') or '')
            hours = float(item.get('kolichestvo_chasov') or 0)

            total_hours += hours
            total_entries += 1

            if emp_id not in employee_map:
                employee_map[emp_id] = {
                    "employee_id": emp_id,
                    "employee_name": user_map.get(emp_id, f"Сотрудник {emp_id}" if emp_id else "Без сотрудника"),
                    "total_hours": 0.0,
                    "entry_count": 0,
                    "projects": set(),
                    "tasks": set(),
                    "project_hours": {},
                    "task_hours": {}
                }

            employee = employee_map[emp_id]
            employee["total_hours"] += hours
            employee["entry_count"] += 1
            employee["projects"].add(project_name)
            if task_id:
                employee["tasks"].add(task_id)

            employee["project_hours"][project_name] = employee["project_hours"].get(project_name, 0.0) + hours
            if task_id:
                employee["task_hours"][task_id] = employee["task_hours"].get(task_id, 0.0) + hours

        employee_rows = []
        total_focus_index = 0.0

        for employee in employee_map.values():
            employee_total_hours = employee["total_hours"]
            entry_count = employee["entry_count"]
            project_count = len(employee["projects"])
            task_count = len(employee["tasks"])

            top_project_hours = max(employee["project_hours"].values()) if employee["project_hours"] else 0.0
            focus_index = (top_project_hours / employee_total_hours) if employee_total_hours else 0.0
            avg_entry_hours = (employee_total_hours / entry_count) if entry_count else 0.0

            risk_level = "Низкий"
            if (project_count >= 5 and focus_index < 0.40) or avg_entry_hours < 1.5:
                risk_level = "Высокий"
            elif project_count >= 4 or focus_index < 0.55:
                risk_level = "Средний"

            total_focus_index += focus_index

            employee_rows.append({
                "employee_id": employee["employee_id"],
                "employee_name": employee["employee_name"],
                "project_count": project_count,
                "task_count": task_count,
                "entry_count": entry_count,
                "total_hours": round(employee_total_hours, 2),
                "avg_entry_hours": round(avg_entry_hours, 2),
                "focus_index": round(focus_index, 3),
                "top_project_hours": round(top_project_hours, 2),
                "risk_level": risk_level
            })

        employee_rows.sort(key=lambda row: (row["risk_level"] == "Высокий", row["project_count"], -row["focus_index"]), reverse=True)
        employee_count = len(employee_rows)

        return {
            "summary": {
                "avg_focus_index": round((total_focus_index / employee_count) if employee_count else 0.0, 3),
                "high_switch_employee_count": sum(1 for row in employee_rows if row["project_count"] > 5),
                "high_risk_employee_count": sum(1 for row in employee_rows if row["risk_level"] == "Высокий"),
                "avg_entry_size": round((total_hours / total_entries) if total_entries else 0.0, 2),
                "avg_entries_per_employee": round((total_entries / employee_count) if employee_count else 0.0, 1),
                "employee_count": employee_count
            },
            "employee_rows": employee_rows
        }

    def _parse_datetime(self, value: Any) -> Optional[datetime]:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value

        value_str = str(value).strip()
        if not value_str:
            return None

        try:
            return datetime.fromisoformat(value_str.replace('Z', '+00:00'))
        except ValueError:
            return None


class TimesheetSyncService:
    def __init__(self, client: Client, account: Bitrix24Account, config: Dict[str, Any]):
        self.client = client
        self.account = account
        self.config = config
        self.entity_type_id = config.get('sp_entity_type_id')
        self.processing_service = DataProcessingService(config.get('fields_mapping', {}))

    # Rate limit retry settings
    MAX_RETRIES = 5
    BASE_RETRY_DELAY = 2.0  # seconds
    THROTTLE_DELAY = 0.5    # seconds between successful requests

    def _call_with_retry(self, method: str, params: dict) -> dict:
        """
        Call Bitrix24 API method with retry on rate limit errors.
        Uses exponential backoff: 2s, 4s, 8s, 16s, 32s
        """
        for attempt in range(self.MAX_RETRIES):
            try:
                return self.client._bitrix_token.call_method(method, params)
            except Exception as e:
                error_str = str(e).lower()
                is_rate_limit = (
                    'too many requests' in error_str
                    or 'querylimitexceeded' in error_str
                    or '503' in error_str
                    or '429' in error_str
                    or 'service temporarily unavailable' in error_str
                )

                if is_rate_limit and attempt < self.MAX_RETRIES - 1:
                    delay = self.BASE_RETRY_DELAY * (2 ** attempt)
                    logger.warning(
                        f"Rate limit hit (attempt {attempt + 1}/{self.MAX_RETRIES}). "
                        f"Waiting {delay}s before retry... Error: {e}"
                    )
                    time.sleep(delay)
                else:
                    raise

    def sync_all(self):
        """
        Fetches all items from Bitrix24 and saves them to the database.
        Uses batching to handle 3000+ items.
        Deletes local records that no longer exist in Bitrix24.
        Includes retry with exponential backoff for rate limit errors.
        """
        logger.info(f"Starting sync for account {self.account.pk}")
        
        if not self.entity_type_id:
             logger.error("No SP Entity Type ID configured cannot sync.")
             return 0

        start = 0
        limit = 50
        total_fetched = 0
        all_bitrix_ids = set()

        while True:
            try:
                # 1. Fetch Batch (with retry on rate limit)
                logger.info(f"Fetching batch start={start} for SPA {self.entity_type_id}")
                response = self._call_with_retry(
                    "crm.item.list",
                    {
                        "entityTypeId": self.entity_type_id,
                        "select": ["*", "UF_*"],
                        "order": {"id": "DESC"},
                        "start": start,
                        "limit": limit
                    }
                )
                
                result = response.get('result', {})
                items = result.get('items', [])
                if not items:
                    logger.info("No more items to fetch.")
                    break
                
                # 2. Normalize
                normalized_items = self.processing_service.normalize_items(items)
                
                # Track all bitrix_ids we received
                for item in normalized_items:
                    try:
                        all_bitrix_ids.add(int(item['id_elem']))
                    except (ValueError, KeyError):
                        pass
                
                # 3. Save to DB
                self._save_batch(normalized_items)

                count = len(items)
                total_fetched += count
                start += count
                
                logger.info(f"Processed {count} items. Total: {total_fetched}")

                if count < limit:
                    break
                
                # Throttle to respect Bitrix24 rate limits (~2 req/sec)
                time.sleep(self.THROTTLE_DELAY)
                
            except Exception as e:
                logger.error(f"Sync error at start={start}: {e}")
                raise e

        # 4. Delete orphaned records (exist locally but not in Bitrix24)
        if all_bitrix_ids:
            deleted_count, _ = TimesheetItem.objects.filter(
                bitrix24_account=self.account
            ).exclude(
                bitrix_id__in=all_bitrix_ids
            ).delete()
            if deleted_count > 0:
                logger.info(f"Deleted {deleted_count} orphaned records")

        logger.info(f"Sync complete. Total items: {total_fetched}")
        return total_fetched

    @transaction.atomic
    def _save_batch(self, normalized_items: List[Dict[str, Any]]):
        for item in normalized_items:
            # Map normalized keys to Model fields
            # "id_elem" -> bitrix_id
            # "id_zadachi" -> task_id
            # "sotrudnik_id" -> employee_id
            # "kolichestvo_chasov" -> hours
            # "uchitivaem" -> is_billable
            # "ne_uchitivaemie_chasi" -> non_billable_hours
            # "opisanie" -> description
            # "id_zadach_ierarhiya" -> task_hierarchy_ids
            # "title_zadach_ierarhiya" -> task_hierarchy_titles
            # "project_name" -> project_title
            # "data" -> date_reflection
            
            try:
                bitrix_id = int(item['id_elem'])
                date_reflection = item['data']
                if not date_reflection:
                     # Skip if no date, or set to now? 
                     # normalize_items sets it from FIELD_DATE. If empty, maybe skip?
                     logger.warning(f"Skipping item {bitrix_id} due to missing date")
                     continue

                TimesheetItem.objects.update_or_create(
                    bitrix24_account=self.account,
                    bitrix_id=bitrix_id,
                    defaults={
                        "task_id": item['id_zadachi'],
                        "employee_id": item['sotrudnik_id'],
                        "hours": item['kolichestvo_chasov'],
                        "is_billable": item['uchitivaem'],
                        "non_billable_hours": item['ne_uchitivaemie_chasi'],
                        "description": item['opisanie'],
                        "project_title": item['project_name'],
                        "project_id": item['project_id'],
                        
                        "task_hierarchy_ids": item['id_zadach_ierarhiya'],
                        "task_hierarchy_titles": item['title_zadach_ierarhiya'],
                        "date_reflection": date_reflection,
                        "source_created_at": item.get('source_created_at'),
                    }
                )
            except Exception as e:
                logger.error(f"Error saving item {item.get('id_elem')}: {e}")


class ProjectCardService:
    def __init__(self, client: Optional[Client], account: Bitrix24Account):
        self.client = client or account.client
        self.account = account

    def get_card_data(self, project_id: str) -> Dict[str, Any]:
        if not ensure_project_card_schema():
            raise RuntimeError("Локальная таблица проектов пока недоступна. Повторите позже после завершения миграции.")

        return self.serialize_card(self._get_card(project_id))

    def get_board_data(self) -> Dict[str, Any]:
        cached = cache.get(build_account_cache_key(self.account, "project-board"))
        if cached is not None:
            return cached

        if not ensure_project_card_schema():
            return self.get_fallback_board_data()

        self.refresh_writeoff_stats()
        cards = list(
            get_project_card_queryset(self.account).order_by("is_archived", "project_name")
        )

        active_cards = [card for card in cards if not card.is_archived]

        payload = {
            "stages": [
                {
                    "id": stage,
                    "title": stage,
                    "kind": "auto" if stage in PROJECT_AUTO_STAGES else "manual",
                    "can_drop": stage in PROJECT_MANUAL_STAGES,
                }
                for stage in PROJECT_STAGE_ORDER
            ],
            "cards": [self.serialize_card(card) for card in cards],
            "summary": {
                "total_count": len(cards),
                "active_count": len(active_cards),
                "archived_count": len(cards) - len(active_cards),
                "support_count": sum(1 for card in active_cards if card.is_support),
                "inactive_30_count": sum(1 for card in active_cards if card.stage == PROJECT_STAGE_NO_WRITEOFF_30),
                "inactive_90_count": sum(1 for card in active_cards if card.stage == PROJECT_STAGE_NO_WRITEOFF_90),
            },
        }
        cache.set(build_account_cache_key(self.account, "project-board"), payload, PROJECT_BOARD_CACHE_TTL)
        return payload

    def get_fallback_board_data(self) -> Dict[str, Any]:
        by_project_id, by_project_title = self.collect_writeoff_maps()
        fallback_cards = []

        for group in build_local_project_groups(self.account):
            project_id = ProjectSyncService._get_first(group, "ID", "id")
            project_name = ProjectSyncService._get_first(group, "NAME", "name") or f"Проект {project_id}"
            last_writeoff_at = by_project_id.get(project_id) or by_project_title.get(project_name)
            last_writeoff_days = (timezone.localdate() - last_writeoff_at.date()).days if last_writeoff_at else 0
            stage = PROJECT_STAGE_IN_WORK if last_writeoff_at else PROJECT_STAGE_NEW

            fallback_cards.append({
                "id": f"fallback-{project_id}",
                "project_id": project_id,
                "project_name": project_name,
                "stage": stage,
                "manual_stage": stage,
                "is_archived": False,
                "archived_at": None,
                "project_hours_budget": None,
                "hourly_rate": 0.0,
                "is_support": False,
                "curator_user_id": None,
                "curator_name": None,
                "project_start_date": None,
                "project_end_date": None,
                "company_id": None,
                "company_name": None,
                "our_legal_entity_id": None,
                "our_legal_entity_name": None,
                "last_writeoff_at": last_writeoff_at.isoformat() if last_writeoff_at else None,
                "last_writeoff_days": last_writeoff_days,
                "stage_source": "manual",
                "created_at": None,
                "updated_at": None,
            })

        payload = {
            "stages": [
                {
                    "id": stage,
                    "title": stage,
                    "kind": "auto" if stage in PROJECT_AUTO_STAGES else "manual",
                    "can_drop": stage in PROJECT_MANUAL_STAGES,
                }
                for stage in PROJECT_STAGE_ORDER
            ],
            "cards": sorted(fallback_cards, key=lambda card: card["project_name"]),
            "summary": {
                "total_count": len(fallback_cards),
                "active_count": len(fallback_cards),
                "archived_count": 0,
                "support_count": 0,
                "inactive_30_count": sum(1 for card in fallback_cards if card["stage"] == PROJECT_STAGE_NO_WRITEOFF_30),
                "inactive_90_count": sum(1 for card in fallback_cards if card["stage"] == PROJECT_STAGE_NO_WRITEOFF_90),
            },
            "warning": (
                "Локальная таблица проектов недоступна. Показан временный board по уже загруженным списаниям. "
                "Редактирование и архив могут быть недоступны до завершения миграции."
            ),
        }
        cache.set(build_account_cache_key(self.account, "project-board"), payload, PROJECT_BOARD_CACHE_TTL)
        return payload

    def get_meta(self) -> Dict[str, Any]:
        cache_key = build_account_cache_key(self.account, "project-board-meta")
        cached = cache.get(cache_key)
        if cached and self._meta_has_required_shape(cached) and self._meta_has_options(cached):
            return cached
        if cached is not None:
            cache.delete(cache_key)

        config = self._load_config()
        fallback_employees = self._get_project_card_fallback_options("curator_user_id", "curator_name")
        fallback_companies = self._get_project_card_fallback_options("company_id", "company_name")
        fallback_legal_entities = self._get_project_card_fallback_options("our_legal_entity_id", "our_legal_entity_name")
        directory_employees = self._merge_reference_options(
            BitrixDataService(self.client, config, self.account).fetch_active_users(),
            fallback_employees,
        )
        directory_companies = self._merge_reference_options(
            self.get_companies(),
            fallback_companies,
        )
        directory_legal_entities = self._merge_reference_options(
            self.get_legal_entities(config),
            fallback_legal_entities,
        )
        meta = {
            "filters": {
                "curators": directory_employees,
                "companies": directory_companies,
                "legal_entities": directory_legal_entities,
            },
            "directories": {
                "employees": directory_employees,
                "companies": directory_companies,
                "legal_entities": directory_legal_entities,
            },
            "employees": directory_employees,
            "companies": directory_companies,
            "legal_entities": directory_legal_entities,
        }
        if self._meta_has_options(meta):
            cache.set(cache_key, meta, BITRIX_REFERENCE_CACHE_TTL)
        else:
            cache.delete(cache_key)
        return meta

    def get_homepage_snapshot(self) -> Dict[str, Any]:
        cached = cache.get(build_account_cache_key(self.account, "project-board-homepage"))
        if cached is not None:
            return cached

        board = self.get_board_data()
        cards = board.get("cards", [])
        active_cards = [card for card in cards if not card.get("is_archived")]
        curators_map: Dict[str, Dict[str, str]] = {}

        for card in active_cards:
            curator_id = str(card.get("curator_user_id") or "").strip()
            curator_name = str(card.get("curator_name") or "").strip()
            if curator_id and curator_id not in curators_map:
                curators_map[curator_id] = {
                    "id": curator_id,
                    "name": curator_name or f"Сотрудник {curator_id}",
                }

        risk_cards = sorted(
            [card for card in active_cards if (card.get("last_writeoff_days") or 0) >= 30],
            key=lambda card: (card.get("last_writeoff_days") or 0, card.get("project_name") or ""),
            reverse=True,
        )[:6]

        leakage_rows = self._get_revenue_leakage_rows(limit=5)
        snapshot = {
            "summary": board.get("summary", {}),
            "cards": active_cards,
            "stages": board.get("stages", []),
            "curators": sorted(curators_map.values(), key=lambda item: item["name"]),
            "risk_cards": risk_cards,
            "top_loss_projects": leakage_rows,
            "warning": board.get("warning"),
            "generated_at": timezone.now().isoformat(),
        }
        cache.set(build_account_cache_key(self.account, "project-board-homepage"), snapshot, HOMEPAGE_CACHE_TTL)
        return snapshot

    def _load_config(self) -> Dict[str, Any]:
        return ConfigurationService(self.client, self.account).get_configuration_sync()

    def _get_project_card_fallback_options(self, id_field: str, name_field: str) -> List[Dict[str, Any]]:
        if not ensure_project_card_schema():
            return []

        rows = (
            get_project_card_queryset(self.account)
            .exclude(**{f"{id_field}__isnull": True})
            .exclude(**{id_field: ""})
            .values(id_field, name_field)
            .order_by(name_field)
        )

        seen_ids = set()
        result: List[Dict[str, Any]] = []
        for row in rows:
            option_id = self._clean_str(row.get(id_field))
            option_name = self._clean_str(row.get(name_field))
            if not option_id or option_id in seen_ids:
                continue
            seen_ids.add(option_id)
            result.append({
                "id": option_id,
                "name": option_name or option_id,
                "search_text": " ".join(part for part in [option_name or option_id] if part).strip(),
            })
        return result

    @staticmethod
    def _merge_reference_options(*option_groups: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
        seen_ids = set()
        merged: List[Dict[str, Any]] = []

        for option_group in option_groups:
            if not option_group:
                continue

            for option in option_group:
                option_id = ProjectCardService._clean_str(option.get("id"))
                option_name = ProjectCardService._clean_str(option.get("name"))
                if not option_id or option_id in seen_ids:
                    continue

                seen_ids.add(option_id)
                normalized_option = dict(option)
                normalized_option["id"] = option_id
                normalized_option["name"] = option_name or option_id

                option_inn = ProjectCardService._clean_str(option.get("inn"))
                if option_inn:
                    normalized_option["inn"] = option_inn

                if "is_my_company" in option:
                    normalized_option["is_my_company"] = ProjectCardService._to_bool(option.get("is_my_company"), default=False)

                normalized_option["search_text"] = " ".join(
                    part for part in [
                        normalized_option.get("name"),
                        option_inn,
                        ProjectCardService._clean_str(option.get("search_text")),
                    ]
                    if part
                ).strip()

                merged.append(normalized_option)

        return sorted(merged, key=lambda item: item["name"])

    @staticmethod
    def _has_reference_options(options: Optional[List[Dict[str, str]]]) -> bool:
        return bool(options and len(options) > 0)

    def _meta_has_options(self, meta: Optional[Dict[str, Any]]) -> bool:
        if not meta:
            return False

        directories = meta.get("directories") if isinstance(meta, dict) else None
        if isinstance(directories, dict):
            return any(
                self._has_reference_options(directories.get(key))
                for key in ("employees", "companies")
            )

        return any(
            self._has_reference_options(meta.get(key))
            for key in ("employees", "companies")
        )

    @staticmethod
    def _meta_has_required_shape(meta: Optional[Dict[str, Any]]) -> bool:
        if not isinstance(meta, dict):
            return False

        filters = meta.get("filters")
        directories = meta.get("directories")
        return isinstance(filters, dict) and isinstance(directories, dict)

    def _fetch_references_with_cache(
        self,
        cache_suffix: str,
        fetcher,
        fallback: Optional[List[Dict[str, Any]]] = None,
        ttl: int = BITRIX_REFERENCE_CACHE_TTL,
    ) -> List[Dict[str, Any]]:
        cache_key = build_account_cache_key(self.account, cache_suffix)
        cached = cache.get(cache_key)
        if self._has_reference_options(cached):
            return cached
        if cached == []:
            cache.delete(cache_key)

        live_result: List[Dict[str, Any]] = []
        try:
            live_result = fetcher() or []
        except Exception as exc:
            logger.warning("Reference fetch failed for %s: %s", cache_suffix, exc)

        merged = self._merge_reference_options(live_result, fallback or [])
        if merged:
            cache.set(cache_key, merged, ttl)
        else:
            cache.delete(cache_key)
        return merged

    def get_companies(self) -> List[Dict[str, Any]]:
        return self._fetch_references_with_cache(
            "project-board-companies",
            self._fetch_companies_live,
            fallback=self._get_project_card_fallback_options("company_id", "company_name"),
        )

    def _fetch_companies_live(self, only_my_company: bool = False) -> List[Dict[str, Any]]:
        inn_map = self._fetch_company_inn_map()
        methods = [
            ("crm.item.list", {"entityTypeId": 4, "select": ["id", "title", "isMyCompany"], "order": {"title": "ASC"}}),
            ("crm.company.list", {"select": ["ID", "TITLE", "IS_MY_COMPANY"], "order": {"TITLE": "ASC"}}),
        ]

        for method, params in methods:
            try:
                companies = self._fetch_paginated(method, params)
            except Exception as exc:
                logger.warning("Company fetch failed for %s: %s", method, exc)
                continue
            normalized: List[Dict[str, Any]] = []
            seen_ids = set()

            for company in companies:
                company_id = self._clean_str(company.get("ID") or company.get("id"))
                company_name = self._clean_str(
                    company.get("TITLE")
                    or company.get("title")
                    or company.get("NAME")
                    or company.get("name")
                )
                is_my_company = self._to_bool(company.get("IS_MY_COMPANY") or company.get("isMyCompany"), default=False)
                company_inn = self._clean_str(
                    company.get("RQ_INN")
                    or company.get("rqInn")
                    or company.get("INN")
                    or company.get("inn")
                    or inn_map.get(company_id)
                )
                if not company_id or not company_name or company_id in seen_ids:
                    continue

                if only_my_company and not is_my_company:
                    continue

                seen_ids.add(company_id)
                normalized.append({
                    "id": company_id,
                    "name": company_name,
                    "inn": company_inn,
                    "is_my_company": is_my_company,
                    "search_text": " ".join(part for part in [company_name, company_inn] if part).strip(),
                })

            if normalized:
                return sorted(normalized, key=lambda item: item["name"])

        return []

    def get_legal_entities(self, config: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        return self._fetch_references_with_cache(
            "project-board-legal-entities",
            lambda: self._fetch_companies_live(only_my_company=True),
            fallback=self._get_project_card_fallback_options("our_legal_entity_id", "our_legal_entity_name"),
        )

    def _fetch_company_inn_map(self) -> Dict[str, str]:
        try:
            requisites = self._fetch_paginated(
                "crm.requisite.list",
                {
                    "filter": {"ENTITY_TYPE_ID": 4},
                    "select": ["ENTITY_ID", "RQ_INN"],
                    "order": {"ID": "ASC"},
                }
            )
        except Exception as exc:
            logger.warning("Company requisites fetch failed: %s", exc)
            return {}

        inn_map: Dict[str, str] = {}
        for requisite in requisites:
            entity_id = self._clean_str(requisite.get("ENTITY_ID") or requisite.get("entityId"))
            inn = self._clean_str(requisite.get("RQ_INN") or requisite.get("rqInn"))
            if entity_id and inn and entity_id not in inn_map:
                inn_map[entity_id] = inn

        return inn_map

    def _fetch_legal_entities_live(
        self,
        iblock_type_id: str,
        iblock_id: Optional[Union[int, str]],
        iblock_code: Optional[str],
        socnet_group_id: Optional[Union[int, str]] = None,
    ) -> List[Dict[str, str]]:
        params: Dict[str, Any] = {
            "IBLOCK_TYPE_ID": iblock_type_id,
            "SELECT": ["ID", "NAME"],
        }
        if iblock_id:
            params["IBLOCK_ID"] = int(iblock_id)
        elif iblock_code:
            params["IBLOCK_CODE"] = iblock_code

        if iblock_type_id == "lists_socnet" and socnet_group_id:
            params["SOCNET_GROUP_ID"] = int(socnet_group_id)

        response = self.client._bitrix_token.call_method("lists.element.get", params)
        result = response.get("result", [])
        if not isinstance(result, list):
            result = []

        normalized: List[Dict[str, str]] = []
        seen_ids = set()
        for row in result:
            option_id = self._clean_str(row.get("ID") or row.get("id"))
            option_name = self._clean_str(row.get("NAME") or row.get("name"))
            if not option_id or not option_name or option_id in seen_ids:
                continue

            seen_ids.add(option_id)
            normalized.append({
                "id": option_id,
                "name": option_name,
            })

        return sorted(normalized, key=lambda item: item["name"])

    def _get_revenue_leakage_rows(self, limit: int = 5) -> List[Dict[str, Any]]:
        recent_from = timezone.localdate() - timedelta(days=90)
        queryset = TimesheetItem.objects.filter(
            bitrix24_account=self.account,
            date_reflection__date__gte=recent_from,
        )

        archived_cards = get_project_card_queryset(self.account).filter(is_archived=True)
        archived_project_ids = [
            project_id
            for project_id in archived_cards.values_list("project_id", flat=True)
            if project_id
        ]
        if archived_project_ids:
            queryset = queryset.exclude(project_id__in=archived_project_ids)

        rows = list(
            queryset.values("project_id", "project_title")
            .annotate(
                total_hours=Sum("hours"),
                non_billable_hours=Sum(
                    Case(
                        When(is_billable=False, then=F("hours")),
                        default=Value(0.0),
                        output_field=FloatField(),
                    )
                ),
                billable_hours=Sum(
                    Case(
                        When(is_billable=True, then=F("hours")),
                        default=Value(0.0),
                        output_field=FloatField(),
                    )
                ),
            )
        )

        normalized: List[Dict[str, Any]] = []
        for row in rows:
            project_name = row.get("project_title") or f"Проект {row.get('project_id') or 'без названия'}"
            total_hours = float(row.get("total_hours") or 0.0)
            non_billable_hours = float(row.get("non_billable_hours") or 0.0)
            if total_hours <= 0 or non_billable_hours <= 0:
                continue

            normalized.append({
                "project_id": self._clean_str(row.get("project_id")),
                "project_name": project_name,
                "total_hours": round(total_hours, 2),
                "billable_hours": round(float(row.get("billable_hours") or 0.0), 2),
                "non_billable_hours": round(non_billable_hours, 2),
                "loss_rate": round((non_billable_hours / total_hours) * 100.0, 1),
            })

        normalized.sort(key=lambda item: (item["non_billable_hours"], item["loss_rate"]), reverse=True)
        return normalized[:limit]

    def update_project_card(self, project_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        if not ensure_project_card_schema():
            raise RuntimeError("Локальная таблица проектов пока недоступна. Повторите позже после завершения миграции.")

        card = self._get_card(project_id)
        warning: Optional[str] = None

        next_project_name = self._clean_str(payload.get("project_name")) or card.project_name
        next_curator_user_id = card.curator_user_id
        next_curator_name = card.curator_name
        next_company_id = card.company_id
        next_company_name = card.company_name
        next_legal_entity_id = card.our_legal_entity_id
        next_legal_entity_name = card.our_legal_entity_name
        next_budget = card.project_hours_budget
        next_hourly_rate = card.hourly_rate
        next_is_support = card.is_support
        next_start_date = card.project_start_date
        next_end_date = card.project_end_date

        if "curator_user_id" in payload:
            next_curator_user_id = self._clean_str(payload.get("curator_user_id"))
        if "curator_name" in payload:
            next_curator_name = self._clean_str(payload.get("curator_name"))
        if "company_id" in payload:
            next_company_id = self._clean_str(payload.get("company_id"))
        if "company_name" in payload:
            next_company_name = self._clean_str(payload.get("company_name"))
        if "our_legal_entity_id" in payload:
            next_legal_entity_id = self._clean_str(payload.get("our_legal_entity_id"))
        if "our_legal_entity_name" in payload:
            next_legal_entity_name = self._clean_str(payload.get("our_legal_entity_name"))
        if "project_hours_budget" in payload:
            next_budget = self._to_optional_float(payload.get("project_hours_budget"))
        if "hourly_rate" in payload:
            next_hourly_rate = self._to_float(payload.get("hourly_rate"), default=card.hourly_rate)
        if "is_support" in payload:
            next_is_support = self._to_bool(payload.get("is_support"), default=card.is_support)
        if "project_start_date" in payload:
            next_start_date = self._parse_date(payload.get("project_start_date"))
        if "project_end_date" in payload:
            next_end_date = self._parse_date(payload.get("project_end_date"))

        if next_curator_user_id and not next_curator_name:
            next_curator_name = BitrixDataService(self.client, {}, self.account).fetch_users([next_curator_user_id]).get(next_curator_user_id)
        if next_company_id and not next_company_name:
            next_company_name = card.company_name
        if next_legal_entity_id and not next_legal_entity_name:
            legal_entities = self.get_legal_entities()
            selected = next((item for item in legal_entities if str(item["id"]) == str(next_legal_entity_id)), None)
            next_legal_entity_name = selected["name"] if selected else card.our_legal_entity_name

        bitrix_payload: Dict[str, Any] = {
            "GROUP_ID": int(card.project_id),
        }

        if next_project_name != card.project_name:
            bitrix_payload["NAME"] = next_project_name

        if payload.get("project_start_date"):
            bitrix_payload["PROJECT_DATE_START"] = datetime.combine(next_start_date, datetime.min.time()).isoformat() if next_start_date else None

        if payload.get("project_end_date"):
            bitrix_payload["PROJECT_DATE_FINISH"] = datetime.combine(next_end_date, datetime.min.time()).isoformat() if next_end_date else None

        bitrix_payload = {key: value for key, value in bitrix_payload.items() if value is not None}

        if len(bitrix_payload) > 1:
            try:
                self.client._bitrix_token.call_method("sonet_group.update", bitrix_payload)
            except Exception as exc:
                warning = f"Не удалось полностью синхронизировать изменения с Битрикс24: {exc}"
                logger.warning("Project update Bitrix sync failed for %s: %s", card.project_id, exc)

        card.project_name = next_project_name
        card.project_hours_budget = next_budget
        card.hourly_rate = next_hourly_rate
        card.is_support = next_is_support
        card.curator_user_id = next_curator_user_id
        card.curator_name = next_curator_name
        card.project_start_date = next_start_date
        card.project_end_date = next_end_date
        card.company_id = next_company_id
        card.company_name = next_company_name
        card.our_legal_entity_id = next_legal_entity_id
        card.our_legal_entity_name = next_legal_entity_name
        card.save()
        invalidate_project_runtime_caches(self.account)

        return {
            "card": self.serialize_card(card),
            "warning": warning,
        }

    def update_stage(self, project_id: str, stage: str) -> Dict[str, Any]:
        if not ensure_project_card_schema():
            raise RuntimeError("Локальная таблица проектов пока недоступна. Повторите позже после завершения миграции.")

        if stage not in PROJECT_MANUAL_STAGES:
            raise ValueError("Недопустимая стадия для ручного перевода")

        card = self._get_card(project_id)
        card.stage = stage
        card.manual_stage = stage
        card.stage_source = "manual"
        card.save(update_fields=["stage", "manual_stage", "stage_source", "stage_updated_at", "updated_at"])
        invalidate_project_runtime_caches(self.account)
        return self.serialize_card(card)

    def archive_project(self, project_id: str, is_archived: bool) -> Dict[str, Any]:
        if not ensure_project_card_schema():
            raise RuntimeError("Локальная таблица проектов пока недоступна. Повторите позже после завершения миграции.")

        card = self._get_card(project_id)
        warning: Optional[str] = None

        card.is_archived = bool(is_archived)
        card.archived_at = timezone.now() if card.is_archived else None
        card.save(update_fields=["is_archived", "archived_at", "updated_at"])
        invalidate_project_runtime_caches(self.account)

        try:
            self.client._bitrix_token.call_method(
                "sonet_group.update",
                {
                    "GROUP_ID": int(card.project_id),
                    "CLOSED": "Y" if card.is_archived else "N",
                }
            )
        except Exception as exc:
            warning = f"Локальный архив обновлен, но Битрикс24 вернул ошибку: {exc}"
            logger.warning("Project archive Bitrix sync failed for %s: %s", card.project_id, exc)

        return {
            "card": self.serialize_card(card),
            "warning": warning,
        }

    def refresh_writeoff_stats(self) -> None:
        if not ensure_project_card_schema():
            return

        by_project_id, by_project_title = self.collect_writeoff_maps()
        cards = list(get_project_card_queryset(self.account))
        today = timezone.localdate()
        updated_cards: List[ProjectCard] = []

        for card in cards:
            last_writeoff_at = by_project_id.get(card.project_id)
            if last_writeoff_at is None and card.project_name:
                last_writeoff_at = by_project_title.get(card.project_name)

            last_writeoff_days = (today - last_writeoff_at.date()).days if last_writeoff_at else 0

            if card.last_writeoff_at != last_writeoff_at or card.last_writeoff_days != last_writeoff_days:
                card.last_writeoff_at = last_writeoff_at
                card.last_writeoff_days = last_writeoff_days
                updated_cards.append(card)

        if updated_cards:
            ProjectCard.objects.bulk_update(updated_cards, ["last_writeoff_at", "last_writeoff_days"])

    def collect_writeoff_maps(self) -> Tuple[Dict[str, datetime], Dict[str, datetime]]:
        by_project_id: Dict[str, datetime] = {}
        by_project_title: Dict[str, datetime] = {}

        id_rows = (
            TimesheetItem.objects.filter(bitrix24_account=self.account)
            .exclude(project_id__isnull=True)
            .exclude(project_id="")
            .values("project_id")
            .annotate(last_writeoff_at=Max("date_reflection"))
        )

        for row in id_rows:
            project_id = self._clean_str(row.get("project_id"))
            last_writeoff_at = row.get("last_writeoff_at")
            if project_id and last_writeoff_at:
                by_project_id[project_id] = last_writeoff_at

        title_rows = (
            TimesheetItem.objects.filter(bitrix24_account=self.account)
            .exclude(project_title__isnull=True)
            .exclude(project_title="")
            .values("project_title")
            .annotate(last_writeoff_at=Max("date_reflection"))
        )

        for row in title_rows:
            project_title = self._clean_str(row.get("project_title"))
            last_writeoff_at = row.get("last_writeoff_at")
            if project_title and last_writeoff_at:
                by_project_title[project_title] = last_writeoff_at

        return by_project_id, by_project_title

    def serialize_card(self, card: ProjectCard) -> Dict[str, Any]:
        return {
            "id": str(card.id),
            "project_id": card.project_id,
            "project_name": card.project_name,
            "stage": card.stage,
            "manual_stage": card.manual_stage,
            "is_archived": card.is_archived,
            "archived_at": card.archived_at.isoformat() if card.archived_at else None,
            "project_hours_budget": card.project_hours_budget,
            "hourly_rate": card.hourly_rate,
            "is_support": card.is_support,
            "curator_user_id": card.curator_user_id,
            "curator_name": card.curator_name,
            "project_start_date": card.project_start_date.isoformat() if card.project_start_date else None,
            "project_end_date": card.project_end_date.isoformat() if card.project_end_date else None,
            "company_id": card.company_id,
            "company_name": card.company_name,
            "our_legal_entity_id": card.our_legal_entity_id,
            "our_legal_entity_name": card.our_legal_entity_name,
            "last_writeoff_at": card.last_writeoff_at.isoformat() if card.last_writeoff_at else None,
            "last_writeoff_days": card.last_writeoff_days,
            "stage_source": card.stage_source,
            "created_at": card.created_at.isoformat() if card.created_at else None,
            "updated_at": card.updated_at.isoformat() if card.updated_at else None,
        }

    def _get_card(self, project_id: str) -> ProjectCard:
        return ProjectCard.objects.get(bitrix24_account=self.account, project_id=str(project_id))

    def _fetch_paginated(self, method: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        start = 0
        items: List[Dict[str, Any]] = []

        while True:
            request_params = dict(params)
            request_params["start"] = start
            response = self.client._bitrix_token.call_method(method, request_params)
            batch, next_value = ProjectSyncService.extract_items_from_response(response)

            if not batch:
                break

            items.extend(batch)

            if next_value is None or int(next_value) <= start:
                break

            start = int(next_value)

        return items

    @staticmethod
    def _clean_str(value: Any) -> Optional[str]:
        if value is None:
            return None

        value_str = str(value).strip()
        return value_str or None

    @staticmethod
    def _to_optional_float(value: Any) -> Optional[float]:
        if value in (None, ""):
            return None

        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _to_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _to_bool(value: Any, default: bool = False) -> bool:
        if value is None:
            return default

        if isinstance(value, bool):
            return value

        return str(value).strip().lower() in {"1", "true", "y", "yes", "on"}

    @staticmethod
    def _parse_date(value: Any) -> Optional[date]:
        if value in (None, ""):
            return None

        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value

        try:
            return date.fromisoformat(str(value)[:10])
        except (TypeError, ValueError):
            return None


class ProjectSyncService:
    def __init__(self, client: Client, account: Bitrix24Account):
        self.client = client
        self.account = account
        self.card_service = ProjectCardService(client, account)

    def sync(self) -> Dict[str, Any]:
        warning: Optional[str] = None

        try:
            groups = self.fetch_project_groups()
        except Exception as exc:
            logger.warning("Project sync Bitrix fetch failed, falling back to local timesheets: %s", exc)
            groups = build_local_project_groups(self.account)
            warning = (
                "Не удалось получить список проектов напрямую из Битрикс24. "
                "Использован локальный список по уже загруженным списаниям."
            )

        by_project_id, by_project_title = self.card_service.collect_writeoff_maps()
        owner_ids = {
            str(group.get("OWNER_ID") or group.get("ownerId") or "").strip()
            for group in groups
            if group.get("OWNER_ID") or group.get("ownerId")
        }
        user_map = BitrixDataService(self.client, {}, self.account).fetch_users(list(owner_ids))

        if not ensure_project_card_schema():
            daily_check = ProjectStageAutomationService(self.account).run_daily_check()
            invalidate_project_runtime_caches(self.account)
            result = {
                "status": "success",
                "synced": len(groups),
                "created": 0,
                "updated": 0,
                **daily_check,
                "warning": (
                    "Локальная таблица проектов недоступна, поэтому board собран без сохранения карточек. "
                    "После завершения миграции синхронизация начнет сохранять метаданные."
                ),
            }
            if warning:
                result["warning"] = f"{result['warning']} {warning}"
            return result

        existing_cards = {
            card.project_id: card
            for card in get_project_card_queryset(self.account)
        }

        created = 0
        updated = 0

        for group in groups:
            normalized = self.normalize_project_group(group, user_map, by_project_id, by_project_title)
            project_id = normalized["project_id"]
            if not project_id:
                continue

            existing = existing_cards.get(project_id)
            if existing is None:
                ProjectCard.objects.create(
                    bitrix24_account=self.account,
                    project_id=project_id,
                    project_name=normalized["project_name"],
                    stage=normalized["initial_stage"],
                    manual_stage=normalized["initial_stage"],
                    is_archived=normalized["is_archived"],
                    archived_at=timezone.now() if normalized["is_archived"] else None,
                    curator_user_id=normalized["curator_user_id"],
                    curator_name=normalized["curator_name"],
                    project_start_date=normalized["project_start_date"],
                    project_end_date=normalized["project_end_date"],
                    last_writeoff_at=normalized["last_writeoff_at"],
                    last_writeoff_days=normalized["last_writeoff_days"],
                    stage_source="manual",
                )
                created += 1
                continue

            changed_fields: List[str] = []

            if normalized["project_name"] and existing.project_name != normalized["project_name"]:
                existing.project_name = normalized["project_name"]
                changed_fields.append("project_name")

            if not existing.curator_user_id and normalized["curator_user_id"]:
                existing.curator_user_id = normalized["curator_user_id"]
                changed_fields.append("curator_user_id")

            if not existing.curator_name and normalized["curator_name"]:
                existing.curator_name = normalized["curator_name"]
                changed_fields.append("curator_name")

            if not existing.project_start_date and normalized["project_start_date"]:
                existing.project_start_date = normalized["project_start_date"]
                changed_fields.append("project_start_date")

            if not existing.project_end_date and normalized["project_end_date"]:
                existing.project_end_date = normalized["project_end_date"]
                changed_fields.append("project_end_date")

            if not existing.manual_stage:
                existing.manual_stage = normalized["initial_stage"]
                changed_fields.append("manual_stage")

            if not existing.stage:
                existing.stage = existing.manual_stage or normalized["initial_stage"]
                changed_fields.append("stage")

            if normalized["is_archived"] and not existing.is_archived:
                existing.is_archived = True
                existing.archived_at = existing.archived_at or timezone.now()
                changed_fields.extend(["is_archived", "archived_at"])

            if changed_fields:
                changed_fields.append("updated_at")
                existing.save(update_fields=changed_fields)
                updated += 1

        self.card_service.refresh_writeoff_stats()
        daily_check = ProjectStageAutomationService(self.account).run_daily_check()

        result = {
            "status": "success",
            "synced": len(groups),
            "created": created,
            "updated": updated,
            **daily_check,
        }

        if warning:
            result["warning"] = warning

        invalidate_project_runtime_caches(self.account)
        return result

    def fetch_project_groups(self) -> List[Dict[str, Any]]:
        errors: List[str] = []

        for fetcher in (
            self._fetch_project_groups_via_sonet_group,
            self._fetch_project_groups_via_socialnetwork,
        ):
            try:
                groups = fetcher()
                if groups:
                    return groups
            except Exception as exc:
                error_text = str(exc)
                errors.append(error_text)
                logger.warning("Project sync fetcher %s failed: %s", fetcher.__name__, error_text)

        if errors:
            raise RuntimeError(f"Не удалось загрузить проекты из Битрикс24: {' | '.join(errors)}")

        return []

    def _fetch_project_groups_via_sonet_group(self) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        page = 1
        page_size = 50

        while True:
            response = self.client._bitrix_token.call_method(
                "sonet_group.get",
                {
                    "FILTER": {
                        "PROJECT": "Y",
                    },
                    "SELECT": [
                        "ID",
                        "NAME",
                        "PROJECT",
                        "CLOSED",
                        "OWNER_ID",
                        "PROJECT_DATE_START",
                        "PROJECT_DATE_FINISH",
                    ],
                    "NAV_PARAMS": {
                        "nPageSize": page_size,
                        "iNumPage": page,
                    },
                }
            )

            batch, _ = self.extract_items_from_response(response)
            if not batch:
                break

            for item in batch:
                if self._is_project(item):
                    items.append(item)

            if len(batch) < page_size:
                break

            page += 1

        return items

    def _fetch_project_groups_via_socialnetwork(self) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        start = 0

        while True:
            response = self.client._bitrix_token.call_method(
                "socialnetwork.api.workgroup.list",
                {
                    "filter": {
                        "PROJECT": "Y",
                    },
                    "select": [
                        "ID",
                        "NAME",
                        "PROJECT",
                        "CLOSED",
                        "OWNER_ID",
                        "PROJECT_DATE_START",
                        "PROJECT_DATE_FINISH",
                    ],
                    "start": start,
                }
            )

            batch, next_value = self.extract_items_from_response(response)
            if not batch:
                break

            for item in batch:
                if self._is_project(item):
                    items.append(item)

            if next_value is None or int(next_value) <= start:
                break

            start = int(next_value)

        return items

    def normalize_project_group(
        self,
        group: Dict[str, Any],
        user_map: Dict[str, str],
        by_project_id: Dict[str, datetime],
        by_project_title: Dict[str, datetime],
    ) -> Dict[str, Any]:
        project_id = self._get_first(group, "ID", "id")
        project_name = self._get_first(group, "NAME", "name") or f"Проект {project_id}"
        curator_user_id = self._get_first(group, "OWNER_ID", "ownerId")
        last_writeoff_at = by_project_id.get(project_id) or by_project_title.get(project_name)
        last_writeoff_days = (timezone.localdate() - last_writeoff_at.date()).days if last_writeoff_at else 0
        initial_stage = PROJECT_STAGE_IN_WORK if last_writeoff_at else PROJECT_STAGE_NEW

        return {
            "project_id": project_id,
            "project_name": project_name,
            "curator_user_id": curator_user_id,
            "curator_name": user_map.get(curator_user_id) if curator_user_id else None,
            "project_start_date": ProjectCardService._parse_date(self._get_first(group, "PROJECT_DATE_START", "projectDateStart")),
            "project_end_date": ProjectCardService._parse_date(self._get_first(group, "PROJECT_DATE_FINISH", "projectDateFinish")),
            "is_archived": ProjectCardService._to_bool(self._get_first(group, "CLOSED", "closed"), default=False),
            "last_writeoff_at": last_writeoff_at,
            "last_writeoff_days": last_writeoff_days,
            "initial_stage": initial_stage,
        }

    @staticmethod
    def extract_items_from_response(response: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], Optional[int]]:
        result = response.get("result", [])
        next_value = response.get("next")

        if isinstance(result, dict):
            items = result.get("items")
            if items is None:
                items = result.get("result", [])
            if next_value is None:
                next_value = result.get("next")
        else:
            items = result

        if not isinstance(items, list):
            items = []

        if next_value in ("", False):
            next_value = None

        return items, int(next_value) if next_value is not None else None

    @staticmethod
    def _get_first(source: Dict[str, Any], *keys: str) -> Optional[str]:
        for key in keys:
            value = source.get(key)
            if value is None:
                continue

            value_str = str(value).strip()
            if value_str:
                return value_str

        return None

    @staticmethod
    def _is_project(item: Dict[str, Any]) -> bool:
        project_flag = item.get("PROJECT")
        if project_flag is None:
            return True
        return ProjectCardService._to_bool(project_flag, default=False)


class ProjectStageAutomationService:
    def __init__(self, account: Bitrix24Account):
        self.account = account

    def run_daily_check(self) -> Dict[str, Any]:
        if not ensure_project_card_schema():
            return {
                "status": "ok",
                "checked": 0,
                "moved_to_30_days": 0,
                "moved_to_90_days": 0,
                "returned_to_work": 0,
            }

        ProjectCardService(None, self.account).refresh_writeoff_stats()
        cards = get_project_card_queryset(self.account).filter(is_archived=False)

        checked = 0
        moved_to_30_days = 0
        moved_to_90_days = 0
        returned_to_work = 0

        for card in cards:
            checked += 1
            target_stage = self._resolve_auto_stage(card)

            if target_stage == PROJECT_STAGE_NO_WRITEOFF_30 and card.stage != target_stage:
                card.stage = target_stage
                card.stage_source = "auto"
                card.save(update_fields=["stage", "stage_source", "stage_updated_at", "updated_at"])
                moved_to_30_days += 1
                continue

            if target_stage == PROJECT_STAGE_NO_WRITEOFF_90 and card.stage != target_stage:
                card.stage = target_stage
                card.stage_source = "auto"
                card.save(update_fields=["stage", "stage_source", "stage_updated_at", "updated_at"])
                moved_to_90_days += 1
                continue

            if target_stage is None and card.stage in PROJECT_AUTO_STAGES:
                fallback_stage = card.manual_stage or (PROJECT_STAGE_IN_WORK if card.last_writeoff_at else PROJECT_STAGE_NEW)
                card.stage = fallback_stage
                card.stage_source = "manual"
                card.save(update_fields=["stage", "stage_source", "stage_updated_at", "updated_at"])
                returned_to_work += 1

        invalidate_project_runtime_caches(self.account)
        return {
            "status": "ok",
            "checked": checked,
            "moved_to_30_days": moved_to_30_days,
            "moved_to_90_days": moved_to_90_days,
            "returned_to_work": returned_to_work,
        }

    @staticmethod
    def _resolve_auto_stage(card: ProjectCard) -> Optional[str]:
        if not card.last_writeoff_at:
            return None

        if card.last_writeoff_days >= 90:
            return PROJECT_STAGE_NO_WRITEOFF_90
        if card.last_writeoff_days >= 30:
            return PROJECT_STAGE_NO_WRITEOFF_30
        return None
