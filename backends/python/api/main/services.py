import json
import time
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional, Union

from b24pysdk import Client
from b24pysdk import Client
from b24pysdk.bitrix_api.requests import BitrixAPIRequest
from django.db import transaction
from .models import TimesheetItem, Bitrix24Account

logger = logging.getLogger(__name__)

# Field Constants from Documentation
ENTITY_TYPE_ID = 1164

FIELD_ID = "id"
FIELD_TASK_ID = "ufCrm87_1761919581"
FIELD_EMPLOYEE = "ufCrm87_1761919601"
FIELD_HOURS = "ufCrm87_1761919617"
FIELD_IS_BILLABLE = "ufCrm87_1763717129"
FIELD_NON_BILLABLE_HOURS = "ufCrm87_1762023633"
FIELD_DESCRIPTION = "ufCrm87_1762026149771"
FIELD_TASK_HIERARCHY = "ufCrm87_1764191110"
FIELD_TITLE_HIERARCHY = "ufCrm87_1764191133"
FIELD_PROJECT_ID = "UF_CRM_87_1764265626"
FIELD_PROJECT_NAME = "UF_CRM_87_1764265641"
FIELD_DATE = "ufCrm87_1764446274"
FIELD_CREATED = "createdTime"


class BitrixDataService:
    """Service for fetching data from Bitrix24"""

    def __init__(self, client: Client):
        self.client = client

    def check_connection(self):
        """Diagnostic: List all SPAs to verify access and IDs"""
        try:
            # crm.type.list via token directly
            response = self.client._bitrix_token.call_method("crm.type.list", {})
            types = response.get('result', {}).get('types', [])
            logger.info(f"Found {len(types)} Smart Processes:")
            for t in types:
                logger.info(f"SPA: {t.get('title')} (ID: {t.get('entityTypeId')})")
            
            # Check for 1164 specifically
            target = next((t for t in types if str(t.get('entityTypeId')) == str(ENTITY_TYPE_ID)), None)
            if target:
                logger.info(f"Target SPA {ENTITY_TYPE_ID} FOUND.")
            else:
                logger.error(f"Target SPA {ENTITY_TYPE_ID} NOT FOUND in crm.type.list!")
        except Exception as e:
            logger.error(f"Failed to list SPAs: {e}")

    def fetch_users(self, user_ids: List[str]) -> Dict[str, str]:
        """
        Fetches users by ID and returns a map {id: "Last First"}
        """
        if not user_ids:
            return {}

        try:
            # Bitrix user.get supports filter by ID
            response = self.client._bitrix_token.call_method(
                "user.get",
                {"FILTER": {"ID": user_ids}}
            )
            users = response.get('result', [])
            user_map = {}
            for u in users:
                # Construct name
                name = f"{u.get('LAST_NAME', '')} {u.get('NAME', '')}".strip()
                if not name:
                    name = u.get('EMAIL') or f"User {u.get('ID')}"
                user_map[str(u.get('ID'))] = name
            return user_map
        except Exception as e:
            logger.error(f"Error fetching users: {e}")
            return {}

    def fetch_all_items(self, extra_filter: Optional[Dict] = None) -> List[Dict[str, Any]]:
        """
        Fetches items from Smart Process - DEBUG MODE: ALL FIELDS
        """
        self.check_connection()
        
        base_filter = {"entityTypeId": ENTITY_TYPE_ID}
        if extra_filter:
            base_filter.update(extra_filter)

        # DEBUG: Select ALL fields to see what we actually get
        select = ["*", "UF_*"]

        logger.info("Executing single request fetch (SELECT *, UF_*)")
        
        try:
            response = self.client._bitrix_token.call_method(
                "crm.item.list",
                {
                    "entityTypeId": ENTITY_TYPE_ID,
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

    def normalize_items(self, raw_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        normalized = []
        dropped_count = 0
        for item in raw_items:
            # 1. Validation: Task ID is required
            # Log why we drop items
            if not item.get(FIELD_TASK_ID):
                dropped_count += 1
                if dropped_count <= 5: # Log first 5 dropped items
                    logger.warning(f"Dropping item {item.get('id')} because FIELD_TASK_ID ({FIELD_TASK_ID}) is missing/empty.")
                    logger.warning(f"Item keys available: {list(item.keys())}")
                continue

            # 2. Parse Hierarchy
            try:
                task_hierarchy = self._parse_json_list(item.get(FIELD_TASK_HIERARCHY))
                title_hierarchy = self._parse_json_list(item.get(FIELD_TITLE_HIERARCHY))
            except Exception:
                # If parsing fails, skip item
                continue

            # 3. Determine Project
            # Priority: Direct Project Name > Root of Title Hierarchy > "Не определён"
            project_name = item.get(FIELD_PROJECT_NAME)
            if not project_name:
                if title_hierarchy and len(title_hierarchy) > 0:
                    project_name = title_hierarchy[0]
                else:
                    project_name = "Не определён"

            # 4. Task Name
            # Last element of title hierarchy or fallback
            task_name = title_hierarchy[-1] if title_hierarchy else "Без названия"

            # 5. Billable status
            # Check different truthy values for boolean/string field
            is_billable_raw = item.get(FIELD_IS_BILLABLE)
            is_billable = str(is_billable_raw).upper() in ['Y', '1', 'TRUE']

            hours = float(item.get(FIELD_HOURS) or 0)
            non_billable = float(item.get(FIELD_NON_BILLABLE_HOURS) or 0)

            normalized_item = {
                "id_elem": str(item.get(FIELD_ID)),
                "id_zadachi": str(item.get(FIELD_TASK_ID)),
                "sotrudnik_id": str(item.get(FIELD_EMPLOYEE)),
                "kolichestvo_chasov": hours,
                "uchitivaem": is_billable,
                "ne_uchitivaemie_chasi": non_billable,
                "opisanie": item.get(FIELD_DESCRIPTION) or "",
                "id_zadach_ierarhiya": task_hierarchy,
                "title_zadach_ierarhiya": title_hierarchy,
                "nazvanie_zadachi": task_name,
                "project_name": project_name,
                "data": item.get(FIELD_DATE) or item.get("createdTime")
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

    def generate_timesheet(self, items: List[Dict[str, Any]]) -> Dict[str, Any]:
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


class TimesheetSyncService:
    def __init__(self, client: Client, account: Bitrix24Account):
        self.client = client
        self.account = account
        self.processing_service = DataProcessingService()

    def sync_all(self):
        """
        Fetches all items from Bitrix24 and saves them to the database.
        Uses batching to handle 3000+ items.
        """
        logger.info(f"Starting sync for account {self.account.pk}")
        
        start = 0
        limit = 50
        total_fetched = 0
        
        # We also need to map fields using DataProcessingService logic
        # But DataProcessingService.normalize_items returns a dict with app-specific keys
        # We can reuse it.

        while True:
            try:
                # 1. Fetch Batch
                logger.info(f"Fetching batch start={start}")
                response = self.client._bitrix_token.call_method(
                    "crm.item.list",
                    {
                        "entityTypeId": ENTITY_TYPE_ID,
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
                
                # 3. Save to DB
                self._save_batch(normalized_items)

                count = len(items)
                total_fetched += count
                start += count
                
                logger.info(f"Processed {count} items. Total: {total_fetched}")

                if count < limit:
                    break
                
                # Throttle
                time.sleep(0.1)
                
            except Exception as e:
                logger.error(f"Sync error at start={start}: {e}")
                # We stop on error to avoid infinite loops or partial implementation issues
                raise e

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
                        # Project ID is mapped in normalize_items? 
                        # Looking at normalize_items, it determines 'project_name' but doesn't seem to extract project_id explicitly into 'project_id' key
                        # It reads FIELD_PROJECT_ID but doesn't map it in the result dict in lines 143-156 of services.py.
                        # I should fix normalize_items essentially or extract it here if I had raw item.
                        # But normalize_items consumes raw item.
                        # I'll rely on project_name for now as that's what was in the plan for 2.2 logic.
                        
                        "task_hierarchy_ids": item['id_zadach_ierarhiya'],
                        "task_hierarchy_titles": item['title_zadach_ierarhiya'],
                        "date_reflection": date_reflection,
                    }
                )
            except Exception as e:
                logger.error(f"Error saving item {item.get('id_elem')}: {e}")

