"""Тесты поиска компаний: один запрос с фильтром вместо обхода справочника портала."""
from unittest.mock import patch

from django.core.cache import cache
from django.test import Client as HttpClient, SimpleTestCase, TestCase
from django.urls import reverse

from .models import Bitrix24Account
from .company_search_service import CompanySearchService, _safe_int


class _FakeClient:
    def __init__(self, responses=None):
        self._responses = dict(responses or {})
        self.calls = []
        self._bitrix_token = self

    def call_method(self, method, params=None):
        self.calls.append((method, params or {}))
        value = self._responses.get(method, {"result": []})
        if isinstance(value, Exception):
            raise value
        return value

    def methods_called(self):
        return [m for m, _ in self.calls]


class CompanySearchTest(TestCase):
    def setUp(self):
        cache.clear()
        self.account = Bitrix24Account.objects.create(
            b24_user_id=1, is_b24_user_admin=True, member_id="m-search-1",
            is_master_account=True, domain_url="example.bitrix24.ru",
            status="active", application_version=1,
        )

    def service(self, client):
        return CompanySearchService(client, self.account)

    def test_short_query_does_not_touch_bitrix(self):
        client = _FakeClient()
        result = self.service(client).search("а")

        self.assertEqual(result["companies"], [])
        self.assertEqual(client.methods_called(), [])

    def test_blank_query_does_not_touch_bitrix(self):
        client = _FakeClient()
        result = self.service(client).search("   ")

        self.assertEqual(result["companies"], [])
        self.assertEqual(client.methods_called(), [])

    def test_search_by_title_makes_one_filtered_call(self):
        client = _FakeClient({
            "crm.company.list": {"result": [
                {"ID": "15", "TITLE": "АО Ромашка"},
                {"ID": "16", "TITLE": "АО Ромашка-2"},
            ]},
        })
        result = self.service(client).search("Ромашка")

        self.assertEqual([c["id"] for c in result["companies"]], ["15", "16"])
        self.assertEqual(client.methods_called(), ["crm.company.list"])
        _, params = client.calls[0]
        self.assertEqual(params["filter"]["%TITLE"], "Ромашка")

    def test_ten_digit_query_also_searches_by_inn(self):
        client = _FakeClient({
            "crm.company.list": {"result": []},
            "crm.requisite.list": {"result": [{"ENTITY_ID": "15", "RQ_INN": "7701234567"}]},
        })
        result = self.service(client).search("7701234567")

        self.assertIn("crm.requisite.list", client.methods_called())

    def test_five_digit_query_does_not_search_by_inn(self):
        client = _FakeClient({"crm.company.list": {"result": []}})
        self.service(client).search("12345")

        self.assertNotIn("crm.requisite.list", client.methods_called())

    def test_limit_caps_results_and_sets_truncated(self):
        rows = [{"ID": str(i), "TITLE": f"Компания {i}"} for i in range(1, 61)]
        client = _FakeClient({"crm.company.list": {"result": rows}})
        result = self.service(client).search("Компания", limit=50)

        self.assertEqual(len(result["companies"]), 50)
        self.assertTrue(result["truncated"])

    def test_bitrix_failure_returns_empty_list_not_exception(self):
        client = _FakeClient({"crm.company.list": RuntimeError("портал недоступен")})
        result = self.service(client).search("Ромашка")

        self.assertEqual(result["companies"], [])
        self.assertTrue(result["failed"])

    def test_repeated_query_is_served_from_cache(self):
        client = _FakeClient({"crm.company.list": {"result": [{"ID": "15", "TITLE": "АО Ромашка"}]}})
        service = self.service(client)
        service.search("Ромашка")
        service.search("Ромашка")

        self.assertEqual(client.methods_called().count("crm.company.list"), 1)

    def test_twelve_digit_query_also_searches_by_inn(self):
        client = _FakeClient({
            "crm.company.list": {"result": []},
            "crm.requisite.list": {"result": [{"ENTITY_ID": "22", "RQ_INN": "770123456789"}]},
        })
        result = self.service(client).search("770123456789")

        self.assertIn("crm.requisite.list", client.methods_called())

    def test_zero_limit_is_clamped_to_one_not_defaulted_to_fifty(self):
        rows = [{"ID": str(i), "TITLE": f"Компания {i}"} for i in range(1, 4)]
        client = _FakeClient({"crm.company.list": {"result": rows}})
        result = self.service(client).search("Компания", limit=0)

        self.assertEqual(len(result["companies"]), 1)
        self.assertTrue(result["truncated"])

    def test_truncated_true_when_bitrix_reports_more_pages_even_at_page_size(self):
        rows = [{"ID": str(i), "TITLE": f"Компания {i}"} for i in range(1, 51)]
        client = _FakeClient({
            "crm.company.list": {"result": rows, "next": 50, "total": 4000},
        })
        result = self.service(client).search("Компания", limit=50)

        self.assertEqual(len(result["companies"]), 50)
        self.assertTrue(result["truncated"])

    def test_dict_result_shape_does_not_crash_and_marks_failed(self):
        client = _FakeClient({"crm.company.list": {"result": {"unexpected": "shape"}}})
        result = self.service(client).search("Ромашка")
        result_again = self.service(client).search("Ромашка")

        self.assertEqual(result["companies"], [])
        self.assertTrue(result["failed"])
        self.assertEqual(result_again["companies"], [])
        self.assertTrue(result_again["failed"])
        # Сбой формы ответа тоже не должен кэшироваться.
        self.assertEqual(client.methods_called().count("crm.company.list"), 2)

    def test_string_result_shape_does_not_crash_and_marks_failed(self):
        client = _FakeClient({"crm.company.list": {"result": "abc"}})
        result = self.service(client).search("Ромашка")

        self.assertEqual(result["companies"], [])
        self.assertTrue(result["failed"])

    def test_list_of_strings_result_does_not_crash_and_marks_failed(self):
        client = _FakeClient({"crm.company.list": {"result": ["a", "b", "c"]}})
        result = self.service(client).search("Ромашка")

        self.assertEqual(result["companies"], [])
        self.assertTrue(result["failed"])

    def test_mixed_type_list_result_does_not_crash_and_marks_failed(self):
        client = _FakeClient({"crm.company.list": {"result": ["a", 42, None, {"nested": True}]}})
        result = self.service(client).search("Ромашка")

        self.assertEqual(result["companies"], [])
        self.assertTrue(result["failed"])

    def test_empty_string_limit_defaults_without_crashing(self):
        rows = [{"ID": str(i), "TITLE": f"Компания {i}"} for i in range(1, 4)]
        client = _FakeClient({"crm.company.list": {"result": rows}})
        result = self.service(client).search("Компания", limit="")

        self.assertEqual(len(result["companies"]), 3)
        self.assertFalse(result["truncated"])

    def test_non_numeric_limit_defaults_without_crashing(self):
        rows = [{"ID": str(i), "TITLE": f"Компания {i}"} for i in range(1, 4)]
        client = _FakeClient({"crm.company.list": {"result": rows}})
        result = self.service(client).search("Компания", limit="many")

        self.assertEqual(len(result["companies"]), 3)
        self.assertFalse(result["truncated"])

    def test_negative_limit_is_clamped_to_one_without_crashing(self):
        rows = [{"ID": str(i), "TITLE": f"Компания {i}"} for i in range(1, 4)]
        client = _FakeClient({"crm.company.list": {"result": rows}})
        result = self.service(client).search("Компания", limit=-5)

        self.assertEqual(len(result["companies"]), 1)
        self.assertTrue(result["truncated"])

    def test_false_limit_is_clamped_to_one_without_crashing(self):
        rows = [{"ID": str(i), "TITLE": f"Компания {i}"} for i in range(1, 4)]
        client = _FakeClient({"crm.company.list": {"result": rows}})
        result = self.service(client).search("Компания", limit=False)

        self.assertEqual(len(result["companies"]), 1)
        self.assertTrue(result["truncated"])

    def test_non_numeric_total_does_not_crash(self):
        rows = [{"ID": str(i), "TITLE": f"Компания {i}"} for i in range(1, 51)]
        client = _FakeClient({
            "crm.company.list": {"result": rows, "total": "many"},
        })
        result = self.service(client).search("Компания", limit=50)

        self.assertEqual(len(result["companies"]), 50)

    def test_inn_lookup_survives_garbage_after_valid_entry(self):
        client = _FakeClient({
            "crm.company.list": {"result": []},
            "crm.requisite.list": {"result": [
                {"ENTITY_ID": "15", "RQ_INN": "7701234567"},
                "trash",
                {"ENTITY_ID": "16", "RQ_INN": "7709876543"},
            ]},
        })
        result = self.service(client).search("7701234567")

        # Мусор в середине списка не должен обрывать разбор: запись ДО и
        # запись ПОСЛЕ мусора обе должны попасть в результат — независимо от
        # порядка, а не только если мусор оказался последним элементом.
        self.assertEqual(sorted(c["id"] for c in result["companies"]), ["15", "16"])
        self.assertTrue(result["failed"])


class MyCompaniesTest(TestCase):
    def setUp(self):
        cache.clear()
        self.account = Bitrix24Account.objects.create(
            b24_user_id=1, is_b24_user_admin=True, member_id="m-mycomp-1",
            is_master_account=True, domain_url="example.bitrix24.ru",
            status="active", application_version=1,
        )

    def test_filters_on_bitrix_side_without_paging_whole_directory(self):
        client = _FakeClient({
            "crm.company.list": {"result": [{"ID": "7", "TITLE": "ООО Мейнсофт"}]},
        })
        result = CompanySearchService(client, self.account).list_my_companies()

        self.assertEqual([c["id"] for c in result["companies"]], ["7"])
        self.assertEqual(client.methods_called(), ["crm.company.list"])
        _, params = client.calls[0]
        self.assertEqual(params["filter"]["IS_MY_COMPANY"], "Y")

    def test_second_call_is_served_from_cache(self):
        client = _FakeClient({"crm.company.list": {"result": [{"ID": "7", "TITLE": "ООО Мейнсофт"}]}})
        service = CompanySearchService(client, self.account)
        service.list_my_companies()
        service.list_my_companies()

        self.assertEqual(client.methods_called().count("crm.company.list"), 1)

    def test_bitrix_failure_returns_empty_list_not_exception(self):
        client = _FakeClient({"crm.company.list": RuntimeError("нет прав")})
        result = CompanySearchService(client, self.account).list_my_companies()

        self.assertEqual(result["companies"], [])
        self.assertTrue(result["failed"])

    def test_dict_result_shape_does_not_crash_and_marks_failed(self):
        client = _FakeClient({"crm.company.list": {"result": {"unexpected": "shape"}}})
        result = CompanySearchService(client, self.account).list_my_companies()
        result_again = CompanySearchService(client, self.account).list_my_companies()

        self.assertEqual(result["companies"], [])
        self.assertTrue(result["failed"])
        self.assertEqual(result_again["companies"], [])
        self.assertTrue(result_again["failed"])
        # Сбой формы ответа тоже не должен кэшироваться.
        self.assertEqual(client.methods_called().count("crm.company.list"), 2)

    def test_string_result_shape_does_not_crash_and_marks_failed(self):
        client = _FakeClient({"crm.company.list": {"result": "abc"}})
        result = CompanySearchService(client, self.account).list_my_companies()

        self.assertEqual(result["companies"], [])
        self.assertTrue(result["failed"])

    def test_list_of_strings_result_does_not_crash_and_marks_failed(self):
        client = _FakeClient({"crm.company.list": {"result": ["a", "b", "c"]}})
        result = CompanySearchService(client, self.account).list_my_companies()

        self.assertEqual(result["companies"], [])
        self.assertTrue(result["failed"])

    def test_mixed_type_list_result_does_not_crash_and_marks_failed(self):
        client = _FakeClient({"crm.company.list": {"result": ["a", 42, None, {"nested": True}]}})
        result = CompanySearchService(client, self.account).list_my_companies()

        self.assertEqual(result["companies"], [])
        self.assertTrue(result["failed"])


class SafeIntOverflowTest(SimpleTestCase):
    """`_safe_int` разбирает total/limit и обязан пережить любой мусор, включая
    float('inf')/float('nan'): response.json() по умолчанию принимает
    Infinity/-Infinity/NaN как валидные числа, так что поле total в ответе
    Битрикса может прийти именно такими значениями (не гипотетический ввод)."""

    def test_positive_infinity_returns_default(self):
        self.assertEqual(_safe_int(float("inf"), 0), 0)

    def test_negative_infinity_returns_default(self):
        self.assertEqual(_safe_int(float("-inf"), 7), 7)

    def test_nan_returns_default(self):
        self.assertEqual(_safe_int(float("nan"), 3), 3)


class SearchTotalOverflowTest(TestCase):
    """Интеграционная проверка той же проблемы на уровне search(): total,
    дошедший как float('inf')/nan, разбирается вне try/except вокруг самого
    HTTP-вызова Битрикса — до фикса OverflowError вылетал необработанным и
    ронял весь запрос (см. SafeIntOverflowTest на уровень ниже)."""

    def setUp(self):
        cache.clear()
        self.account = Bitrix24Account.objects.create(
            b24_user_id=1, is_b24_user_admin=True, member_id="m-search-total-inf-1",
            is_master_account=True, domain_url="search-total-inf.bitrix24.ru",
            status="active", application_version=1,
        )

    def service(self, client):
        return CompanySearchService(client, self.account)

    def test_infinite_total_does_not_crash_search(self):
        rows = [{"ID": str(i), "TITLE": f"Компания {i}"} for i in range(1, 4)]
        client = _FakeClient({"crm.company.list": {"result": rows, "total": float("inf")}})

        result = self.service(client).search("Компания", limit=50)

        self.assertEqual(len(result["companies"]), 3)

    def test_negative_infinite_total_does_not_crash_search(self):
        rows = [{"ID": str(i), "TITLE": f"Компания {i}"} for i in range(1, 4)]
        client = _FakeClient({"crm.company.list": {"result": rows, "total": float("-inf")}})

        result = self.service(client).search("Компания", limit=50)

        self.assertEqual(len(result["companies"]), 3)

    def test_nan_total_does_not_crash_search(self):
        rows = [{"ID": str(i), "TITLE": f"Компания {i}"} for i in range(1, 4)]
        client = _FakeClient({"crm.company.list": {"result": rows, "total": float("nan")}})

        result = self.service(client).search("Компания", limit=50)

        self.assertEqual(len(result["companies"]), 3)


class NoneResultIsNotCachedAsSuccessTest(TestCase):
    """{"result": None} — не пустой список ("ничего не нашлось"), а неожиданный
    ответ Битрикса. Раньше _normalize_rows считал его успехом, и такой ответ
    кэшировался: для search() — на SEARCH_CACHE_TTL (5 минут), а для
    list_my_companies() — на MY_COMPANIES_CACHE_TTL (6 часов), то есть один
    странный ответ мог спрятать юрлица на полдня."""

    def setUp(self):
        cache.clear()
        self.account = Bitrix24Account.objects.create(
            b24_user_id=1, is_b24_user_admin=True, member_id="m-none-result-1",
            is_master_account=True, domain_url="none-result.bitrix24.ru",
            status="active", application_version=1,
        )

    def test_search_none_result_is_marked_failed_and_not_cached(self):
        client = _FakeClient({"crm.company.list": {"result": None}})
        service = CompanySearchService(client, self.account)

        first = service.search("Ромашка")
        self.assertEqual(first["companies"], [])
        self.assertTrue(first["failed"])

        # Второй вызов обязан снова опросить Битрикс — неудачный разбор не
        # должен был попасть в кэш.
        client.calls.clear()
        service.search("Ромашка")
        self.assertEqual(client.methods_called(), ["crm.company.list"])

    def test_list_my_companies_none_result_is_marked_failed_and_not_cached(self):
        client = _FakeClient({"crm.company.list": {"result": None}})
        service = CompanySearchService(client, self.account)

        first = service.list_my_companies()
        self.assertEqual(first["companies"], [])
        self.assertTrue(first["failed"])

        client.calls.clear()
        service.list_my_companies()
        self.assertEqual(client.methods_called(), ["crm.company.list"])


class CompanySearchEndpointRoutingTest(TestCase):
    """Task 5, шаг 1: маршруты существуют и оба отклоняют POST."""

    def test_search_route_resolves_to_expected_path(self):
        self.assertEqual(
            reverse("search_project_board_companies"),
            "/api/project-board/companies/search",
        )

    def test_my_companies_route_resolves_to_expected_path(self):
        self.assertEqual(reverse("list_my_companies"), "/api/project-board/my-companies")

    def test_search_endpoint_rejects_post(self):
        response = HttpClient().post("/api/project-board/companies/search")
        self.assertEqual(response.status_code, 405)

    def test_my_companies_endpoint_rejects_post(self):
        response = HttpClient().post("/api/project-board/my-companies")
        self.assertEqual(response.status_code, 405)


class SearchEndpointHttpTest(TestCase):
    """Разбор ?limit= обязан пережить любой мусор — проверено прогоном через
    реальный HTTP-запрос (Django test client), а не только вызовом
    CompanySearchService.search() напрямую в сервисных тестах выше.
    request.GET.get("limit") на "?limit=" без значения отдаёт пустую строку,
    а не None — план уже дважды ловил дефекты именно в разборе входных
    значений на границе HTTP, поэтому это отдельно зафиксировано здесь."""

    def setUp(self):
        cache.clear()
        self.http = HttpClient()
        self.account = Bitrix24Account.objects.create(
            b24_user_id=1, is_b24_user_admin=True, member_id="m-search-http-1",
            is_master_account=True, domain_url="search-http.bitrix24.ru",
            status="active", application_version=1,
        )
        self.auth_header = f"Bearer {self.account.create_jwt_token()}"

    def _get(self, query_suffix=""):
        url = "/api/project-board/companies/search"
        if query_suffix:
            url = f"{url}?{query_suffix}"
        return self.http.get(url, HTTP_AUTHORIZATION=self.auth_header)

    def test_no_params_returns_200_without_touching_bitrix(self):
        # Пустой q короче MIN_QUERY_LENGTH -> честный сквозной прогон без
        # моков: URL -> view -> request.GET.get -> CompanySearchService.search
        # -> _parse_limit, короткое замыкание случается уже ПОСЛЕ разбора limit.
        response = self._get()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"companies": [], "truncated": False, "failed": False})

    def test_garbage_limit_values_never_crash_the_endpoint(self):
        # q="a" короче MIN_QUERY_LENGTH -> короткое замыкание после разбора
        # limit и до обращения к Битриксу, поэтому и это без моков.
        garbage_values = ("", "0", "-5", "abc", "1.5", "99999999999999999999", "%%%", "[]", "inf")
        for garbage in garbage_values:
            response = self._get(f"q=a&limit={garbage}")
            self.assertEqual(
                response.status_code, 200,
                f"limit={garbage!r} не должен ронять эндпоинт, получили {response.status_code}",
            )

    def test_empty_limit_value_reaches_service_as_empty_string_not_none(self):
        with patch.object(
            CompanySearchService, "search",
            return_value={"companies": [], "truncated": False, "failed": False},
        ) as mocked:
            response = self._get("q=Ромашка&limit=")

        self.assertEqual(response.status_code, 200)
        # Критичный момент задачи: request.GET.get("limit") на "?limit=" без
        # значения отдаёт "" (пустую строку), а не None — сюда это доходит
        # без изменений, разбирает уже сервис (_parse_limit).
        mocked.assert_called_once_with("Ромашка", limit="")

    def test_missing_limit_param_reaches_service_as_none(self):
        with patch.object(
            CompanySearchService, "search",
            return_value={"companies": [], "truncated": False, "failed": False},
        ) as mocked:
            response = self._get("q=Ромашка")

        self.assertEqual(response.status_code, 200)
        mocked.assert_called_once_with("Ромашка", limit=None)

    def test_missing_q_param_reaches_service_as_empty_string(self):
        with patch.object(
            CompanySearchService, "search",
            return_value={"companies": [], "truncated": False, "failed": False},
        ) as mocked:
            response = self._get("limit=10")

        self.assertEqual(response.status_code, 200)
        mocked.assert_called_once_with("", limit="10")


class MyCompaniesEndpointHttpTest(TestCase):
    def setUp(self):
        cache.clear()
        self.http = HttpClient()
        self.account = Bitrix24Account.objects.create(
            b24_user_id=1, is_b24_user_admin=True, member_id="m-mycomp-http-1",
            is_master_account=True, domain_url="mycomp-http.bitrix24.ru",
            status="active", application_version=1,
        )
        self.auth_header = f"Bearer {self.account.create_jwt_token()}"

    def test_returns_service_payload_as_json(self):
        payload = {"companies": [{"id": "7", "name": "ООО Мейнсофт"}], "failed": False}
        with patch.object(CompanySearchService, "list_my_companies", return_value=payload) as mocked:
            response = self.http.get(
                "/api/project-board/my-companies", HTTP_AUTHORIZATION=self.auth_header
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), payload)
        mocked.assert_called_once_with()
