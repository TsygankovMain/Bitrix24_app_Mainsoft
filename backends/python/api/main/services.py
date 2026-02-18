import json
import time
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional, Union

from b24pysdk import Client
from b24pysdk.bitrix_api.requests import BitrixAPIRequest
from django.db import transaction
from .models import TimesheetItem, Bitrix24Account
from .configuration_service import ConfigurationService

logger = logging.getLogger(__name__)

# Field Constants from Documentation
class BitrixDataService:
    """Service for fetching data from Bitrix24"""

    def __init__(self, client: Client, config: Dict[str, Any]):
        self.client = client
        self.config = config
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

            normalized_item = {
                "id_elem": str(item.get('id')),
                "id_zadachi": str(item.get(field_task_id)),
                "sotrudnik_id": str(item.get(field_employee)),
                "kolichestvo_chasov": hours,
                "uchitivaem": is_billable,
                "ne_uchitivaemie_chasi": non_billable,
                "opisanie": item.get(field_desc) or "",
                "id_zadach_ierarhiya": task_hierarchy,
                "title_zadach_ierarhiya": title_hierarchy,
                "nazvanie_zadachi": task_name,
                "project_name": project_name,
                "project_id": str(item.get(field_project_id) or ""),
                "data": item.get(field_date) or item.get("createdTime")
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


class TimesheetSyncService:
    def __init__(self, client: Client, account: Bitrix24Account, config: Dict[str, Any]):
        self.client = client
        self.account = account
        self.config = config
        self.entity_type_id = config.get('sp_entity_type_id')
        self.processing_service = DataProcessingService(config.get('fields_mapping', {}))

    def sync_all(self):
        """
        Fetches all items from Bitrix24 and saves them to the database.
        Uses batching to handle 3000+ items.
        Deletes local records that no longer exist in Bitrix24.
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
                # 1. Fetch Batch
                logger.info(f"Fetching batch start={start} for SPA {self.entity_type_id}")
                response = self.client._bitrix_token.call_method(
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
                
                # Throttle
                time.sleep(0.1)
                
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
                    }
                )
            except Exception as e:
                logger.error(f"Error saving item {item.get('id_elem')}: {e}")

