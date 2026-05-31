"""Тесты сервиса дозаполнения ИНН (Спринт 2, этап A)."""

import os
import unittest
from types import SimpleNamespace
from unittest import mock

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "settings")
django.setup()

from main import inn_backfill_service as svc_mod  # noqa: E402
from main.inn_backfill_service import (  # noqa: E402
    InnBackfillService,
    STATUS_ATTENTION,
    STATUS_NO_PROJECT,
    STATUS_READY,
    build_project_lookup,
    classify_row,
    is_blank,
    resolve_card_inn,
)


class FakeToken:
    def __init__(self):
        self.calls = []

    def call_method(self, method, params):
        self.calls.append((method, params))
        return {"result": {}}


class FakeClient:
    def __init__(self):
        self._bitrix_token = FakeToken()


class PureFnTests(unittest.TestCase):
    def test_is_blank(self):
        for v in (None, "", "   ", [], {}):
            self.assertTrue(is_blank(v), v)
        for v in ("7701", 7701, ["x"], "  7  "):
            self.assertFalse(is_blank(v), v)

    def test_build_project_lookup(self):
        c1 = SimpleNamespace(project_item_id="10", project_id="G1")
        c2 = SimpleNamespace(project_item_id="", project_id="G2")
        by_item, by_id = build_project_lookup([c1, c2])
        self.assertIs(by_item["10"], c1)
        self.assertIs(by_id["G1"], c1)
        self.assertIs(by_id["G2"], c2)
        self.assertNotIn("", by_item)

    def test_resolve_card_inn(self):
        card = SimpleNamespace(company_id="5", our_legal_entity_id="9")
        our, client = resolve_card_inn(card, {"5": "7701234567"}, {"9": "7709876543"})
        self.assertEqual(our, "7709876543")
        self.assertEqual(client, "7701234567")
        self.assertEqual(resolve_card_inn(None, {}, {}), ("", ""))
        # компания без реквизита → пусто
        self.assertEqual(resolve_card_inn(card, {}, {}), ("", ""))

    def test_classify_row(self):
        self.assertEqual(classify_row(True, True, "a", "b", True), STATUS_READY)
        self.assertEqual(classify_row(True, False, "a", "", True), STATUS_READY)
        self.assertEqual(classify_row(False, True, "", "", True), STATUS_ATTENTION)
        self.assertEqual(classify_row(True, True, "", "b", True), STATUS_ATTENTION)
        self.assertEqual(classify_row(True, True, "a", "b", False), STATUS_NO_PROJECT)


class ApplyTests(unittest.TestCase):
    def setUp(self):
        svc_mod.THROTTLE_DELAY = 0  # не спать в тестах
        cfg = {"sp_entity_type_id": 123,
               "fields_mapping": {"our_inn": "UF_OUR", "client_inn": "UF_CLIENT"}}
        self.svc = InnBackfillService(FakeClient(), object(), cfg)

    def test_apply_writes_only_nonblank(self):
        res = self.svc.apply([
            {"bitrix_id": 1, "our_inn": "7709876543", "client_inn": "7701234567"},
            {"bitrix_id": 2, "our_inn": "", "client_inn": "7702000000"},
            {"bitrix_id": 3},  # ничего → пропуск
        ])
        self.assertEqual(res["updated"], 2)
        self.assertEqual(res["failed"], [])
        calls = self.svc.client._bitrix_token.calls
        self.assertEqual(len(calls), 2)
        method, params = calls[0]
        self.assertEqual(method, "crm.item.update")
        self.assertEqual(params["id"], 1)
        self.assertEqual(params["entityTypeId"], 123)
        self.assertEqual(params["fields"], {"UF_OUR": "7709876543", "UF_CLIENT": "7701234567"})
        # вторая запись — только клиентский ИНН
        self.assertEqual(calls[1][1]["fields"], {"UF_CLIENT": "7702000000"})

    def test_ensure_inn_fields(self):
        self.assertIsNone(self.svc.ensure_inn_fields())
        bad = InnBackfillService(FakeClient(), object(),
                                 {"sp_entity_type_id": 1, "fields_mapping": {}})
        self.assertIsNotNone(bad.ensure_inn_fields())
        no_sp = InnBackfillService(FakeClient(), object(), {})
        self.assertIn("Смарт-процесс", no_sp.ensure_inn_fields())

    def test_apply_truncates_large_batch(self):
        items = [{"bitrix_id": i, "client_inn": "7701234567"} for i in range(1, 151)]
        res = self.svc.apply(items)
        self.assertTrue(res["truncated"])
        self.assertEqual(res["updated"], 100)  # MAX_APPLY_BATCH


class ScanTests(unittest.TestCase):
    def setUp(self):
        svc_mod.THROTTLE_DELAY = 0
        self.card = SimpleNamespace(
            project_item_id="100", project_id="G1",
            company_id="C1", our_legal_entity_id="L1", project_name="Проект А")
        self.companies = {"C1": "7701234567"}
        self.legal = {"L1": "7709876543"}
        self.items = [
            {"id": 1, "UF_PITEM": "100", "UF_OUR": "", "UF_CLIENT": "", "UF_EMP": "e1", "UF_TASK": ["Задача"], "UF_DATE": "2026-05-03"},
            {"id": 2, "UF_PITEM": "100", "UF_OUR": "x", "UF_CLIENT": "y"},  # уже заполнена → пропуск
            {"id": 3, "UF_PITEM": "999", "UF_OUR": "", "UF_CLIENT": ""},     # нет проекта
        ]

    def _service(self):
        cfg = {"sp_entity_type_id": 123, "fields_mapping": {
            "our_inn": "UF_OUR", "client_inn": "UF_CLIENT", "project_id": "UF_PID",
            "project_item_id": "UF_PITEM", "sotrudnik": "UF_EMP",
            "title_zadach_ierarhiya": "UF_TASK", "opisanie": "UF_DESC", "data": "UF_DATE"}}
        svc = InnBackfillService(FakeClient(), object(), cfg)
        svc._fetch_cards = lambda df, dt: self.items
        svc._inn_maps = lambda: (self.companies, self.legal)
        svc._resolve_employee_names = lambda ids: {"e1": "Иванов И."}
        return svc

    @mock.patch("main.inn_backfill_service.get_project_card_queryset")
    def test_scan_groups_kpi_and_status(self, m_qs):
        m_qs.return_value = [self.card]
        res = self._service().scan("2026-05-01", "2026-05-31")
        self.assertEqual(res["kpi"]["total"], 3)
        self.assertEqual(res["kpi"]["without_inn"], 2)
        self.assertEqual(res["kpi"]["resolvable"], 1)
        self.assertEqual(res["kpi"]["attention"], 1)
        self.assertIsNone(res["warning"])
        keys = {g["key"] for g in res["groups"]}
        self.assertEqual(keys, {"G1", "__no_project__"})
        g1 = next(g for g in res["groups"] if g["key"] == "G1")
        self.assertEqual(g1["project_name"], "Проект А")
        self.assertEqual(g1["our_inn"], "7709876543")
        self.assertEqual(g1["client_inn"], "7701234567")
        self.assertEqual(g1["rows"][0]["status"], "ready")
        self.assertEqual(g1["rows"][0]["employee_name"], "Иванов И.")
        gnp = next(g for g in res["groups"] if g["key"] == "__no_project__")
        self.assertEqual(gnp["rows"][0]["status"], "no_project")

    @mock.patch("main.inn_backfill_service.get_project_card_queryset")
    def test_scan_warns_on_degraded_resolution(self, m_qs):
        m_qs.return_value = [self.card]
        svc = self._service()
        svc._inn_maps = lambda: ({}, {})  # реквизиты недоступны
        res = svc.scan("2026-05-01", "2026-05-31")
        self.assertIsNotNone(res["warning"])

    @mock.patch("main.inn_backfill_service.get_project_card_queryset")
    def test_autofill_resolves_and_writes(self, m_qs):
        m_qs.return_value = [self.card]
        svc = self._service()
        res = svc.autofill([
            {"bitrix_id": 1, "project_item_id": "100", "project_id": "G1"},  # резолвится
            {"bitrix_id": 2, "project_item_id": "999", "project_id": "X"},   # нет проекта → пропуск
        ])
        self.assertEqual(res["resolved"], 1)
        self.assertEqual(res["updated"], 1)
        calls = svc.client._bitrix_token.calls
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1]["id"], 1)
        self.assertEqual(calls[0][1]["fields"], {"UF_OUR": "7709876543", "UF_CLIENT": "7701234567"})


if __name__ == "__main__":
    unittest.main()
