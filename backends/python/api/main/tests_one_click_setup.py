"""Тесты настройки «в одно нажатие» (main.one_click_setup_service).

Сценарий собирает то, что раньше администратор проходил шестью шагами экрана
«Сопоставление полей»: три смарт-процесса (часы, проекты, доходы-расходы), все
их поля, стадии воронки проектов и сохранение конфигурации. Главные обещания:

  1. на чистом портале после одного вызова приложение настроено целиком;
  2. повторный вызов ничего не дублирует и не ломает;
  3. то, что администратор настроил руками, не перезаписывается;
  4. отказ на одном блоке не теряет уже сделанное в других.

Портал подменён состоянием в памяти (_FakePortal): он помнит созданные типы,
поля и стадии, поэтому тесты проверяют итог, а не порядок вызовов.
"""
import json

from django.core.cache import cache
from django.test import SimpleTestCase

from .installation_service import (
    FINANCE_FIELD_DEFINITIONS,
    PROJECT_FIELD_DEFINITIONS,
    TIMESHEET_FIELD_DEFINITIONS,
)
from .one_click_setup_service import OneClickSetupBusy, OneClickSetupService
from .project_board_shared import (
    PROJECT_STAGE_ESTIMATE,
    PROJECT_STAGE_IN_WORK,
    PROJECT_STAGE_NEW,
    PROJECT_STAGE_NO_WRITEOFF_30,
    PROJECT_STAGE_NO_WRITEOFF_90,
)


class _FakePortal:
    """Портал Битрикс24 в памяти: типы, пользовательские поля, стадии, app.option."""

    def __init__(self):
        self.option = None
        self.types = []                  # {id, entityTypeId, title, code}
        self.fields = {}                 # entityTypeId -> {apiId: meta}
        self.statuses = {}               # ENTITY_ID -> [row]
        self.calls = []
        self.fail = {}                   # method -> Exception | callable(params) -> Exception | None
        self._next_ordinal = 5
        self._next_etid = 1038
        self._next_status_id = 100

    # -- заготовки состояния -------------------------------------------------
    def add_type(self, code, title="Свой процесс"):
        ordinal, etid = self._next_ordinal, self._next_etid
        self._next_ordinal += 1
        self._next_etid += 2
        self.types.append({"id": ordinal, "entityTypeId": etid, "title": title, "code": code})
        self.fields[etid] = {}
        entity = f"DYNAMIC_{etid}_STAGE_{ordinal + 10}"
        self.statuses[entity] = [
            self._status(entity, etid, ordinal + 10, "NEW", "Начало", 10, ""),
            self._status(entity, etid, ordinal + 10, "PREPARATION", "Подготовка", 20, ""),
            self._status(entity, etid, ordinal + 10, "CLIENT", "Клиент", 30, ""),
            self._status(entity, etid, ordinal + 10, "SUCCESS", "Успех", 40, "S"),
            self._status(entity, etid, ordinal + 10, "FAIL", "Провал", 50, "F"),
        ]
        return etid

    def _status(self, entity, etid, category, code, name, sort, semantics):
        self._next_status_id += 1
        return {"ID": str(self._next_status_id), "ENTITY_ID": entity, "STATUS_ID": f"DT{etid}_{category}:{code}",
                "NAME": name, "SORT": sort, "SEMANTICS": semantics, "CATEGORY_ID": category}

    def config(self):
        return json.loads(self.option) if self.option else {}

    def stage_names(self, etid):
        entity = next(k for k in self.statuses if k.startswith(f"DYNAMIC_{etid}_STAGE_"))
        return [row["NAME"] for row in sorted(self.statuses[entity], key=lambda r: r["SORT"])]

    def count(self, method):
        return sum(1 for name, _ in self.calls if name == method)

    # -- REST ----------------------------------------------------------------
    def call_method(self, method, params=None):
        params = params or {}
        self.calls.append((method, params))
        failure = self.fail.get(method)
        if callable(failure):
            failure = failure(params)
        if isinstance(failure, Exception):
            raise failure
        return getattr(self, "_" + method.replace(".", "_"))(params)

    def _app_option_get(self, params):
        return {"result": {"timestamp_config": self.option} if self.option else {}}

    def _app_option_set(self, params):
        self.option = params["options"]["timestamp_config"]
        return {"result": True}

    def _crm_type_list(self, params):
        return {"result": {"types": list(self.types)}}

    def _crm_type_add(self, params):
        fields = params["fields"]
        etid = self.add_type(fields["code"], fields["title"])
        return {"result": {"type": {"entityTypeId": etid}}}

    def _crm_type_getByEntityTypeId(self, params):
        row = next(t for t in self.types if t["entityTypeId"] == int(params["entityTypeId"]))
        return {"result": {"type": dict(row)}}

    def _crm_category_list(self, params):
        etid = int(params["entityTypeId"])
        entity = next(k for k in self.statuses if k.startswith(f"DYNAMIC_{etid}_STAGE_"))
        return {"result": {"categories": [{"id": int(entity.rsplit("_", 1)[1]), "isDefault": "Y"}]}}

    def _userfieldconfig_add(self, params):
        field = params["field"]
        ordinal = int(field["entityId"].split("_")[1])
        etid = next(t["entityTypeId"] for t in self.types if t["id"] == ordinal)
        parts = field["fieldName"].split("_")
        api_id = "".join(p.lower() if i == 0 else p[:1].upper() + p[1:].lower() for i, p in enumerate(parts))
        if api_id in self.fields[etid]:
            raise RuntimeError("Field already exists")
        self.fields[etid][api_id] = {"title": field["fieldName"], "type": field["userTypeId"]}
        return {"result": {"field": {"fieldName": field["fieldName"]}}}

    def _crm_item_fields(self, params):
        return {"result": {"fields": dict(self.fields.get(int(params["entityTypeId"]), {}))}}

    def _crm_status_list(self, params):
        return {"result": list(self.statuses.get(params["filter"]["ENTITY_ID"], []))}

    def _crm_status_update(self, params):
        for rows in self.statuses.values():
            for row in rows:
                if row["ID"] == str(params["id"]):
                    row.update(params["fields"])
        return {"result": True}

    def _crm_status_add(self, params):
        fields = dict(params["fields"])
        self._next_status_id += 1
        fields["ID"] = str(self._next_status_id)
        self.statuses[fields["ENTITY_ID"]].append(fields)
        return {"result": int(fields["ID"])}


class _FakeClient:
    def __init__(self, portal):
        self._bitrix_token = portal


class _Account:
    member_id = "member-one-click"
    portal_id = None
    pk = 1


def _run(portal):
    return OneClickSetupService(_FakeClient(portal), _Account()).run()


class OneClickSetupCleanPortalTest(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.portal = _FakePortal()
        self.report = _run(self.portal)
        self.config = self.portal.config()

    def test_three_smart_processes_created_and_saved(self):
        codes = sorted(t["code"] for t in self.portal.types)
        self.assertEqual(codes, ["finance_app", "project_app", "timesheet_app"])
        by_code = {t["code"]: t["entityTypeId"] for t in self.portal.types}
        self.assertEqual(self.config["sp_entity_type_id"], by_code["timesheet_app"])
        self.assertEqual(self.config["project_sp_entity_type_id"], by_code["project_app"])
        self.assertEqual(self.config["finance_sp_entity_type_id"], by_code["finance_app"])

    def test_every_field_is_mapped(self):
        self.assertEqual(set(self.config["fields_mapping"]), set(TIMESHEET_FIELD_DEFINITIONS))
        self.assertEqual(set(self.config["finance_fields_mapping"]), set(FINANCE_FIELD_DEFINITIONS))
        project_mapping = self.config["project_fields_mapping"]
        for key in list(PROJECT_FIELD_DEFINITIONS) + ["title"]:
            self.assertTrue(project_mapping.get(key), key)
        self.assertEqual(project_mapping["title"], "TITLE")
        self.assertEqual(project_mapping["stage_id"], "STAGE_ID")

    def test_app_is_marked_configured(self):
        self.assertTrue(self.config["is_configured"])
        self.assertEqual(self.report["status"], "done")

    def test_project_stages_match_what_the_board_expects(self):
        etid = self.config["project_sp_entity_type_id"]
        self.assertEqual(
            self.portal.stage_names(etid),
            [PROJECT_STAGE_NEW, PROJECT_STAGE_ESTIMATE, PROJECT_STAGE_IN_WORK,
             PROJECT_STAGE_NO_WRITEOFF_30, PROJECT_STAGE_NO_WRITEOFF_90, "Успех", "Провал"],
        )

    def test_new_stages_carry_their_funnel(self):
        # Стадия без CATEGORY_ID видна в канбане, но невидима для автоматизации портала.
        etid = self.config["project_sp_entity_type_id"]
        entity = next(k for k in self.portal.statuses if k.startswith(f"DYNAMIC_{etid}_STAGE_"))
        category = int(entity.rsplit("_", 1)[1])
        added = [r for r in self.portal.statuses[entity] if r["NAME"] in (PROJECT_STAGE_NO_WRITEOFF_30, PROJECT_STAGE_NO_WRITEOFF_90)]
        self.assertEqual(len(added), 2)
        for row in added:
            self.assertEqual(int(row["CATEGORY_ID"]), category)
            self.assertTrue(row["STATUS_ID"].startswith(f"DT{etid}_{category}:"))

    def test_timesheet_stages_are_left_alone(self):
        self.assertEqual(self.portal.stage_names(self.config["sp_entity_type_id"])[0], "Начало")

    def test_report_lists_each_block(self):
        blocks = {b["block"]: b for b in self.report["blocks"]}
        self.assertEqual(set(blocks), {"timesheet", "project", "finance"})
        self.assertTrue(all(b["created"] and b["ready"] for b in blocks.values()))

    def test_second_run_changes_nothing(self):
        before = (len(self.portal.types), {k: len(v) for k, v in self.portal.fields.items()},
                  {k: len(v) for k, v in self.portal.statuses.items()})
        report = _run(self.portal)
        after = (len(self.portal.types), {k: len(v) for k, v in self.portal.fields.items()},
                 {k: len(v) for k, v in self.portal.statuses.items()})
        self.assertEqual(before, after)
        self.assertEqual(report["status"], "done")
        self.assertFalse(any(b["created"] for b in report["blocks"]))
        self.assertEqual(self.portal.count("crm.type.add"), 3)


class OneClickSetupRespectsManualWorkTest(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.portal = _FakePortal()

    def test_configured_process_and_manual_mapping_are_kept(self):
        etid = self.portal.add_type("", "Часы нашей компании")
        self.portal.fields[etid]["ufCrm5MyHours"] = {"title": "Мои часы", "type": "double"}
        self.portal.option = json.dumps({"sp_entity_type_id": etid, "fields_mapping": {"kolichestvo_chasov": "ufCrm5MyHours"}})

        _run(self.portal)
        config = self.portal.config()

        self.assertEqual(config["sp_entity_type_id"], etid)
        self.assertEqual(config["fields_mapping"]["kolichestvo_chasov"], "ufCrm5MyHours")
        self.assertEqual(set(config["fields_mapping"]), set(TIMESHEET_FIELD_DEFINITIONS))
        self.assertNotIn("ufCrm5Hours", self.portal.fields[etid])     # дубль своего поля не заводим
        self.assertEqual(sum(1 for t in self.portal.types if t["code"] == "timesheet_app"), 0)

    def test_process_left_from_earlier_install_is_reused(self):
        # Приложение переустановили: конфигурация пуста, а процесс с нашим кодом на портале остался.
        etid = self.portal.add_type("project_app", "Проекты (App)")
        _run(self.portal)
        self.assertEqual(self.portal.config()["project_sp_entity_type_id"], etid)
        self.assertEqual(sum(1 for t in self.portal.types if t["code"] == "project_app"), 1)

    def test_stages_of_existing_project_process_are_not_renamed(self):
        etid = self.portal.add_type("project_app", "Проекты (App)")
        _run(self.portal)
        self.assertEqual(self.portal.stage_names(etid)[:3], ["Начало", "Подготовка", "Клиент"])


class OneClickSetupFailureTest(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.portal = _FakePortal()

    def test_failed_block_does_not_lose_the_others(self):
        self.portal.fail["crm.type.add"] = lambda p: RuntimeError("Достигнут лимит смарт-процессов") if p["fields"]["code"] == "finance_app" else None
        report = _run(self.portal)
        config = self.portal.config()

        self.assertEqual(report["status"], "partial")
        blocks = {b["block"]: b for b in report["blocks"]}
        self.assertTrue(blocks["timesheet"]["ready"] and blocks["project"]["ready"])
        self.assertFalse(blocks["finance"]["ready"])
        self.assertIn("лимит", blocks["finance"]["error"])
        self.assertTrue(config["sp_entity_type_id"] and config["project_sp_entity_type_id"])
        self.assertFalse(config.get("finance_sp_entity_type_id"))

    def test_stage_failure_is_a_warning_not_an_error(self):
        self.portal.fail["crm.status.add"] = RuntimeError("Access denied")
        report = _run(self.portal)
        project = next(b for b in report["blocks"] if b["block"] == "project")
        self.assertTrue(project["ready"])
        self.assertTrue(any("Access denied" in w for w in project["warnings"]))

    def test_parallel_run_is_refused(self):
        service = OneClickSetupService(_FakeClient(self.portal), _Account())
        self.assertTrue(cache.add(service.lock_key, "1", 60))
        with self.assertRaises(OneClickSetupBusy):
            service.run()
        self.assertEqual(self.portal.count("crm.type.add"), 0)
