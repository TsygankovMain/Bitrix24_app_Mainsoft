import json
from django.test import SimpleTestCase
from .services import DataProcessingService, ReportService, FIELD_TASK_ID, FIELD_EMPLOYEE, FIELD_HOURS, FIELD_PROJECT_NAME, FIELD_TASK_HIERARCHY, FIELD_TITLE_HIERARCHY, FIELD_DATE

class ReportServiceTest(SimpleTestCase):
    def test_normalization_project_logic(self):
        processor = DataProcessingService()
        
        # Case 1: Direct Project Name
        item1 = {
            FIELD_TASK_ID: "1",
            FIELD_PROJECT_NAME: "Project A",
            FIELD_TITLE_HIERARCHY: '["Root", "Sub"]'
        }
        norm1 = processor.normalize_items([item1])[0]
        self.assertEqual(norm1["project_name"], "Project A")
        
        # Case 2: Hierarchy Fallback
        item2 = {
            FIELD_TASK_ID: "2",
            FIELD_PROJECT_NAME: "",
            FIELD_TITLE_HIERARCHY: '["Project B", "Sub"]'
        }
        norm2 = processor.normalize_items([item2])[0]
        self.assertEqual(norm2["project_name"], "Project B")
        
        # Case 3: No Project
        item3 = {
            FIELD_TASK_ID: "3",
            FIELD_PROJECT_NAME: None,
            FIELD_TITLE_HIERARCHY: '[]'
        }
        norm3 = processor.normalize_items([item3])[0]
        self.assertEqual(norm3["project_name"], "Не определён")

    def test_report_aggregation(self):
        reporter = ReportService()
        
        items = [
            {
                "sotrudnik_id": "user1",
                "project_name": "Project A",
                "kolichestvo_chasov": 5.0,
                "data": "2023-10-01T00:00:00+03:00"
            },
            {
                "sotrudnik_id": "user1",
                "project_name": "Project A",
                "kolichestvo_chasov": 3.0,
                "data": "2023-10-02T00:00:00+03:00"
            },
            {
                "sotrudnik_id": "user2",
                "project_name": "Project B",
                "kolichestvo_chasov": 2.0,
                "data": "2023-10-01T00:00:00+03:00"
            }
        ]
        
        # Test Employee -> Project
        emp_report = reporter.generate_employee_projects(items)
        # Expect 2 employees
        self.assertEqual(len(emp_report), 2)
        # User1: 8 hours
        # Sort or find
        user1 = next(u for u in emp_report if u["id"] == "user1")
        self.assertEqual(user1["total_hours"], 8.0)
        # Project A in User1: 8 hours
        projA = next(p for p in user1["projects"] if p["name"] == "Project A")
        self.assertEqual(projA["total_hours"], 8.0)
        
        # Test Timesheet
        ts_report = reporter.generate_timesheet(items)
        # User1: Total 8, day 1: 5, day 2: 3
        ts_user1 = next(u for u in ts_report if u["employee_id"] == "user1")
        self.assertEqual(ts_user1["total"], 8.0)
        self.assertEqual(ts_user1["days"]["1"], 5.0)
        self.assertEqual(ts_user1["days"]["2"], 3.0)
