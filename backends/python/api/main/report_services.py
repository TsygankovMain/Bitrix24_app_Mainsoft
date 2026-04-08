import json
import logging
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional


logger = logging.getLogger(__name__)

FIELD_TASK_ID = "id_zadachi"
FIELD_TASK_HIERARCHY = "id_zadach_ierarhiya"
FIELD_TITLE_HIERARCHY = "title_zadach_ierarhiya"
FIELD_PROJECT_NAME = "project_title"
FIELD_PROJECT_ID = "project_id"
FIELD_IS_BILLABLE = "uchitivaem"
FIELD_HOURS = "kolichestvo_chasov"
FIELD_NON_BILLABLE_HOURS = "ne_uchitivaemie_chasi"
FIELD_DESCRIPTION = "opisanie"
FIELD_EMPLOYEE = "sotrudnik"
FIELD_DATE = "data"

DEFAULT_FIELDS_MAPPING = {
    FIELD_TASK_ID: FIELD_TASK_ID,
    FIELD_TASK_HIERARCHY: FIELD_TASK_HIERARCHY,
    FIELD_TITLE_HIERARCHY: FIELD_TITLE_HIERARCHY,
    "project_title": FIELD_PROJECT_NAME,
    FIELD_PROJECT_ID: FIELD_PROJECT_ID,
    FIELD_IS_BILLABLE: FIELD_IS_BILLABLE,
    FIELD_HOURS: FIELD_HOURS,
    FIELD_NON_BILLABLE_HOURS: FIELD_NON_BILLABLE_HOURS,
    FIELD_DESCRIPTION: FIELD_DESCRIPTION,
    FIELD_EMPLOYEE: FIELD_EMPLOYEE,
    FIELD_DATE: FIELD_DATE,
}


class DataProcessingService:
    """Service for normalizing and processing raw Bitrix24 data."""

    def __init__(self, mapping: Optional[Dict[str, str]] = None):
        self.mapping = {**DEFAULT_FIELDS_MAPPING, **(mapping or {})}

    def normalize_items(self, raw_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        normalized = []
        dropped_count = 0

        def get_f(key: str) -> Optional[str]:
            return self.mapping.get(key)

        field_task_id = get_f(FIELD_TASK_ID)
        field_task_hierarchy = get_f(FIELD_TASK_HIERARCHY)
        field_title_hierarchy = get_f(FIELD_TITLE_HIERARCHY)
        field_project_name = get_f("project_title")
        field_project_id = get_f(FIELD_PROJECT_ID)
        field_is_billable = get_f(FIELD_IS_BILLABLE)
        field_hours = get_f(FIELD_HOURS)
        field_non_billable = get_f(FIELD_NON_BILLABLE_HOURS)
        field_desc = get_f(FIELD_DESCRIPTION)
        field_employee = get_f(FIELD_EMPLOYEE)
        field_date = get_f(FIELD_DATE)

        for item in raw_items:
            if not field_task_id or not item.get(field_task_id):
                dropped_count += 1
                continue

            try:
                task_hierarchy = self._parse_json_list(item.get(field_task_hierarchy))
                title_hierarchy = self._parse_json_list(item.get(field_title_hierarchy))
                hours = self._to_float(item.get(field_hours))
                non_billable = self._to_float(item.get(field_non_billable))
            except ValueError:
                dropped_count += 1
                continue

            project_name = self._stringify_value(item.get(field_project_name))
            if not project_name:
                project_name = title_hierarchy[0] if title_hierarchy else "Не определён"

            task_name = title_hierarchy[-1] if title_hierarchy else "Без названия"

            is_billable_raw = item.get(field_is_billable)
            is_billable = str(is_billable_raw).upper() in ["Y", "1", "TRUE"]

            emp_raw = item.get(field_employee)
            if isinstance(emp_raw, list):
                emp_id = str(emp_raw[0]) if emp_raw else ""
            elif emp_raw is not None:
                emp_id = str(emp_raw).strip()
            else:
                emp_id = ""

            normalized.append(
                {
                    "id_elem": str(item.get("id")),
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
                    "project_id": self._stringify_value(item.get(field_project_id)),
                    "data": item.get(field_date) or item.get("createdTime"),
                    "source_created_at": item.get("createdTime"),
                }
            )

        logger.info(
            "Normalization complete. Input: %s, Output: %s, Dropped: %s",
            len(raw_items),
            len(normalized),
            dropped_count,
        )
        return normalized

    @staticmethod
    def _parse_json_list(json_str: Any) -> List[str]:
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

    @staticmethod
    def _stringify_value(value: Any) -> str:
        if value in (None, ""):
            return ""
        if isinstance(value, list):
            return str(value[0]).strip() if value else ""
        return str(value).strip()

    @staticmethod
    def _to_float(value: Any) -> float:
        if value in (None, "", False):
            return 0.0
        if isinstance(value, (int, float)):
            return float(value)

        normalized = str(value).strip().replace(",", ".")
        if not normalized:
            return 0.0

        try:
            return float(normalized)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid numeric value: {value}") from exc


class ReportService:
    """Service for aggregating reports."""

    def generate_employee_projects(
        self,
        items: List[Dict[str, Any]],
        user_map: Optional[Dict[str, str]] = None,
    ) -> List[Dict[str, Any]]:
        tree = {}
        user_map = user_map or {}

        for item in items:
            emp_id = item["sotrudnik_id"]
            proj_name = item["project_name"] or "Без проекта"

            hours = item["kolichestvo_chasov"]
            is_billable = item.get("uchitivaem", False)
            billable = hours if is_billable else 0.0
            non_billable = hours if not is_billable else 0.0

            if emp_id not in tree:
                tree[emp_id] = {
                    "type": "employee",
                    "id": emp_id,
                    "name": user_map.get(emp_id, f"Сотрудник {emp_id}"),
                    "total_hours": 0.0,
                    "billable_hours": 0.0,
                    "non_billable_hours": 0.0,
                    "children": {},
                }

            emp_node = tree[emp_id]
            emp_node["total_hours"] += hours
            emp_node["billable_hours"] += billable
            emp_node["non_billable_hours"] += non_billable

            if proj_name not in emp_node["children"]:
                emp_node["children"][proj_name] = {
                    "type": "project",
                    "name": proj_name,
                    "total_hours": 0.0,
                    "billable_hours": 0.0,
                    "non_billable_hours": 0.0,
                    "children": {},
                }

            proj_node = emp_node["children"][proj_name]
            proj_node["total_hours"] += hours
            proj_node["billable_hours"] += billable
            proj_node["non_billable_hours"] += non_billable

            t_ids = item.get("id_zadach_ierarhiya") or []
            t_titles = item.get("title_zadach_ierarhiya") or []
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
                        "items": [],
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

    def generate_project_employees(
        self,
        items: List[Dict[str, Any]],
        user_map: Optional[Dict[str, str]] = None,
    ) -> List[Dict[str, Any]]:
        tree = {}
        user_map = user_map or {}

        for item in items:
            emp_id = item["sotrudnik_id"]
            proj_name = item["project_name"] or "Без проекта"

            hours = item["kolichestvo_chasov"]
            is_billable = item.get("uchitivaem", False)
            billable = hours if is_billable else 0.0
            non_billable = hours if not is_billable else 0.0

            if proj_name not in tree:
                tree[proj_name] = {
                    "type": "project",
                    "id": proj_name,
                    "name": proj_name,
                    "total_hours": 0.0,
                    "billable_hours": 0.0,
                    "non_billable_hours": 0.0,
                    "children": {},
                }

            proj_node = tree[proj_name]
            proj_node["total_hours"] += hours
            proj_node["billable_hours"] += billable
            proj_node["non_billable_hours"] += non_billable

            if emp_id not in proj_node["children"]:
                proj_node["children"][emp_id] = {
                    "type": "employee",
                    "id": emp_id,
                    "name": user_map.get(emp_id, f"Сотрудник {emp_id}"),
                    "total_hours": 0.0,
                    "billable_hours": 0.0,
                    "non_billable_hours": 0.0,
                    "children": {},
                }

            emp_node = proj_node["children"][emp_id]
            emp_node["total_hours"] += hours
            emp_node["billable_hours"] += billable
            emp_node["non_billable_hours"] += non_billable

            t_ids = item.get("id_zadach_ierarhiya") or []
            t_titles = item.get("title_zadach_ierarhiya") or []
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
                        "items": [],
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

    def generate_project_task_employees(
        self,
        items: List[Dict[str, Any]],
        user_map: Optional[Dict[str, str]] = None,
    ) -> List[Dict[str, Any]]:
        tree = {}
        user_map = user_map or {}

        for item in items:
            emp_id = item["sotrudnik_id"]
            proj_name = item["project_name"] or "Без проекта"

            hours = item["kolichestvo_chasov"]
            is_billable = item.get("uchitivaem", False)
            billable = hours if is_billable else 0.0
            non_billable = hours if not is_billable else 0.0

            if proj_name not in tree:
                tree[proj_name] = {
                    "type": "project",
                    "id": proj_name,
                    "name": proj_name,
                    "total_hours": 0.0,
                    "billable_hours": 0.0,
                    "non_billable_hours": 0.0,
                    "children": {},
                }

            proj_node = tree[proj_name]
            proj_node["total_hours"] += hours
            proj_node["billable_hours"] += billable
            proj_node["non_billable_hours"] += non_billable

            t_ids = item.get("id_zadach_ierarhiya") or []
            t_titles = item.get("title_zadach_ierarhiya") or []
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
                        "employees": {},
                    }

                task_node = current_level_children[t_id]
                task_node["total_hours"] += hours
                task_node["billable_hours"] += billable
                task_node["non_billable_hours"] += non_billable

                if idx == len(t_ids) - 1:
                    if emp_id not in task_node["employees"]:
                        task_node["employees"][emp_id] = {
                            "type": "employee",
                            "id": emp_id,
                            "name": user_map.get(emp_id, f"Сотрудник {emp_id}"),
                            "total_hours": 0.0,
                            "billable_hours": 0.0,
                            "non_billable_hours": 0.0,
                            "items": [],
                        }

                    emp_node = task_node["employees"][emp_id]
                    emp_node["total_hours"] += hours
                    emp_node["billable_hours"] += billable
                    emp_node["non_billable_hours"] += non_billable
                    emp_node["items"].append(item)
                else:
                    current_level_children = task_node["children"]

        return self._convert_pte_tree(tree)

    def generate_timesheet(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Matrix: Employee vs day of month."""
        report = {}

        for item in items:
            emp_id = item["sotrudnik_id"]
            hours = item["kolichestvo_chasov"]
            date_str = item["data"]

            if not date_str:
                continue

            try:
                dt = datetime.fromisoformat(date_str)
                day_key = str(dt.day)
            except ValueError:
                continue

            if emp_id not in report:
                report[emp_id] = {"employee_id": emp_id, "total": 0.0, "days": {}}

            report[emp_id]["total"] += hours
            report[emp_id]["days"][day_key] = report[emp_id]["days"].get(day_key, 0.0) + hours

        return list(report.values())

    def generate_daily_workload(
        self,
        items: List[Dict[str, Any]],
        user_map: Dict[str, str],
        date_from: str,
        date_to: str,
    ) -> Dict[str, Any]:
        try:
            start_date = date.fromisoformat(date_from)
            end_date = date.fromisoformat(date_to)
        except (ValueError, TypeError):
            today = date.today()
            start_date = date(today.year, today.month, 1)
            end_date = today

        header_days = []
        current_day = start_date
        while current_day <= end_date:
            header_days.append(
                {
                    "date": current_day.isoformat(),
                    "day": current_day.day,
                    "weekday": current_day.weekday(),
                    "is_weekend": current_day.weekday() >= 5,
                }
            )
            current_day += timedelta(days=1)

        agg = {}
        for item in items:
            emp_id = item["sotrudnik_id"]
            date_str = item["data"]
            if not date_str:
                continue

            try:
                item_date = datetime.fromisoformat(date_str).date()
            except ValueError:
                continue

            if not (start_date <= item_date <= end_date):
                continue

            date_key = item_date.isoformat()
            if emp_id not in agg:
                agg[emp_id] = {
                    "id": emp_id,
                    "name": user_map.get(emp_id, f"User {emp_id}"),
                    "days": {},
                }

            if date_key not in agg[emp_id]["days"]:
                agg[emp_id]["days"][date_key] = {"total": 0.0, "items": []}

            hours = float(item["kolichestvo_chasov"] or 0)
            agg[emp_id]["days"][date_key]["total"] += hours
            agg[emp_id]["days"][date_key]["items"].append(
                {
                    "task_id": item["id_zadachi"],
                    "task_title": item["nazvanie_zadachi"],
                    "project_title": item["project_name"],
                    "hours": hours,
                    "description": item["opisanie"],
                }
            )

        rows = []
        for emp_id, data in agg.items():
            row_days = {}
            for day_obj in header_days:
                date_key = day_obj["date"]
                day_data = data["days"].get(date_key, {"total": 0.0, "items": []})
                total = day_data["total"]
                if total == 0:
                    status = "neutral"
                elif total < 6:
                    status = "orange"
                elif total <= 9:
                    status = "green"
                else:
                    status = "yellow"

                row_days[date_key] = {
                    "total": round(total, 2),
                    "status": status,
                    "items": day_data["items"],
                }

            rows.append(
                {
                    "employee": {"id": emp_id, "name": data["name"]},
                    "days": row_days,
                }
            )

        rows.sort(key=lambda item: item["employee"]["name"])
        return {"header_days": header_days, "rows": rows}

    def generate_revenue_leakage(
        self,
        items: List[Dict[str, Any]],
        user_map: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        user_map = user_map or {}
        project_map: Dict[str, Dict[str, Any]] = {}
        employee_totals: Dict[str, Dict[str, Any]] = {}

        total_hours = 0.0
        total_billable = 0.0
        total_non_billable = 0.0

        for item in items:
            emp_id = str(item.get("sotrudnik_id") or "")
            project_name = item.get("project_name") or "Без проекта"
            hours = float(item.get("kolichestvo_chasov") or 0)
            is_billable = bool(item.get("uchitivaem", False))
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
                    "employees": {},
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
                employee_totals[emp_id] = {"total_hours": 0.0, "non_billable_hours": 0.0}

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
                risk_rows.append(
                    {
                        "project_name": project["name"],
                        "employee_id": employee["employee_id"],
                        "employee_name": employee["employee_name"],
                        "total_hours": round(employee_total, 2),
                        "billable_hours": round(employee["billable_hours"], 2),
                        "non_billable_hours": round(employee["non_billable_hours"], 2),
                        "loss_rate": round(employee_loss_rate, 1),
                    }
                )

            employees.sort(key=lambda row: (row["non_billable_hours"], row["loss_rate"]), reverse=True)
            project_rows.append(
                {
                    "name": project["name"],
                    "total_hours": round(project_total, 2),
                    "billable_hours": round(project["billable_hours"], 2),
                    "non_billable_hours": round(project["non_billable_hours"], 2),
                    "loss_rate": round(project_loss_rate, 1),
                    "employee_count": len(employees),
                    "employees": employees,
                }
            )

        project_rows.sort(key=lambda row: (row["non_billable_hours"], row["loss_rate"]), reverse=True)
        risk_rows.sort(key=lambda row: (row["non_billable_hours"], row["loss_rate"]), reverse=True)

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
                "high_risk_project_count": sum(1 for row in project_rows if row["loss_rate"] >= 30.0 and row["total_hours"] > 0),
                "high_risk_employee_count": high_risk_employee_count,
            },
            "project_rows": project_rows,
            "risk_rows": risk_rows,
        }

    def generate_time_entry_discipline(
        self,
        items: List[Dict[str, Any]],
        user_map: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        user_map = user_map or {}
        buckets = {"0": 0, "1": 0, "2": 0, "3": 0, "4+": 0}
        employee_map: Dict[str, Dict[str, Any]] = {}

        total_entries = 0
        same_day_count = 0
        next_day_count = 0
        two_plus_count = 0
        total_lag_days = 0.0
        fallback_entries = 0

        for item in items:
            emp_id = str(item.get("sotrudnik_id") or "")
            reflection_dt = self._parse_datetime(item.get("date_reflection"))
            source_created_at = self._parse_datetime(item.get("source_created_at"))

            if source_created_at is None:
                source_created_at = self._parse_datetime(item.get("created_at"))
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

            employee_rows.append(
                {
                    "employee_id": employee["employee_id"],
                    "employee_name": employee["employee_name"],
                    "entry_count": entry_count,
                    "same_day_share": round(same_day_share, 3),
                    "avg_lag_days": round(avg_lag_days, 1),
                    "late_entries": employee["late_entries"],
                    "max_lag_days": employee["max_lag_days"],
                    "last_late_entry_date": employee["last_late_entry_date"],
                    "risk_level": risk_level,
                }
            )

        employee_rows.sort(
            key=lambda row: (row["avg_lag_days"], row["late_entries"], -row["same_day_share"]),
            reverse=True,
        )

        return {
            "summary": {
                "total_entries": total_entries,
                "same_day_share": round((same_day_count / total_entries) if total_entries else 0.0, 3),
                "next_day_share": round((next_day_count / total_entries) if total_entries else 0.0, 3),
                "two_plus_share": round((two_plus_count / total_entries) if total_entries else 0.0, 3),
                "avg_lag_days": round((total_lag_days / total_entries) if total_entries else 0.0, 1),
                "retro_entries": two_plus_count,
                "high_risk_employee_count": sum(1 for row in employee_rows if row["risk_level"] == "Высокий"),
                "fallback_entries": fallback_entries,
            },
            "lag_buckets": [
                {"label": "0д", "count": buckets["0"]},
                {"label": "1д", "count": buckets["1"]},
                {"label": "2д", "count": buckets["2"]},
                {"label": "3д", "count": buckets["3"]},
                {"label": "4+д", "count": buckets["4+"]},
            ],
            "employee_rows": employee_rows,
        }

    def generate_focus_analysis(
        self,
        items: List[Dict[str, Any]],
        user_map: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        user_map = user_map or {}
        employee_map: Dict[str, Dict[str, Any]] = {}
        total_hours = 0.0
        total_entries = 0

        for item in items:
            emp_id = str(item.get("sotrudnik_id") or "")
            project_name = item.get("project_name") or "Без проекта"
            task_id = str(item.get("id_zadachi") or item.get("task_id") or "")
            hours = float(item.get("kolichestvo_chasov") or 0)

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
                    "task_hours": {},
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
            employee_rows.append(
                {
                    "employee_id": employee["employee_id"],
                    "employee_name": employee["employee_name"],
                    "project_count": project_count,
                    "task_count": task_count,
                    "entry_count": entry_count,
                    "total_hours": round(employee_total_hours, 2),
                    "avg_entry_hours": round(avg_entry_hours, 2),
                    "focus_index": round(focus_index, 3),
                    "top_project_hours": round(top_project_hours, 2),
                    "risk_level": risk_level,
                }
            )

        employee_rows.sort(
            key=lambda row: (row["risk_level"] == "Высокий", row["project_count"], -row["focus_index"]),
            reverse=True,
        )
        employee_count = len(employee_rows)

        return {
            "summary": {
                "avg_focus_index": round((total_focus_index / employee_count) if employee_count else 0.0, 3),
                "high_switch_employee_count": sum(1 for row in employee_rows if row["project_count"] > 5),
                "high_risk_employee_count": sum(1 for row in employee_rows if row["risk_level"] == "Высокий"),
                "avg_entry_size": round((total_hours / total_entries) if total_entries else 0.0, 2),
                "avg_entries_per_employee": round((total_entries / employee_count) if employee_count else 0.0, 1),
                "employee_count": employee_count,
            },
            "employee_rows": employee_rows,
        }

    def _convert_tree_to_list(self, nodes_dict: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
        result = []
        for node in nodes_dict.values():
            if "children" in node:
                node["children"] = self._convert_tree_to_list(node["children"])
            result.append(node)
        return result

    def _convert_pte_tree(self, nodes_dict: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
        result = []
        for node in nodes_dict.values():
            if "children" in node:
                node["children"] = self._convert_pte_tree(node["children"])
            if "employees" in node:
                node["employees"] = list(node["employees"].values())
            result.append(node)
        return result

    @staticmethod
    def _parse_datetime(value: Any) -> Optional[datetime]:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value

        value_str = str(value).strip()
        if not value_str:
            return None

        try:
            return datetime.fromisoformat(value_str.replace("Z", "+00:00"))
        except ValueError:
            return None
