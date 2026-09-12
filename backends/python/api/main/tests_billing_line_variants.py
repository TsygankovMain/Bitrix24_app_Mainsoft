"""Четыре варианта наполнения счёта: состав строк, формулировки, источник.

Зачем этот файл. Вариант наполнения был зашит в код («по задачам»), а
формулировка строки — одна на все четыре варианта. Порталу, выставляющему
одной строкой, приходилось переключать вариант в каждом счёте руками и читать
в документе «Услуги по договору, август 2026» — то есть шаблон варианта «по
задачам», натянутый на строку, у которой задачи нет.

Пять вещей, которые обязаны держаться:

1. каждый из четырёх вариантов даёт свой СОСТАВ строк и свою ФОРМУЛИРОВКУ по
   умолчанию, и формулировки не путаются между собой;
2. СУММА документа от варианта не зависит: одна и та же выборка при любом
   варианте даёт те же часы и те же деньги — вариант про читаемость счёта, а
   не про деньги;
3. вариант по умолчанию задаёт НАСТРОЙКА ПОРТАЛА, а выбор в мастере её
   перекрывает, и ответ говорит, который из двух источников сработал;
4. подстановки ``{сотрудник}`` и ``{услуга}`` работают, а ``{проект}`` и
   ``{сотрудник}`` в строке из нескольких проектов (или от нескольких людей)
   честно пустеют, а не называют первый попавшийся;
5. настройки читаются из конфигурации приложения, причём одиночный
   ``billing_line_template`` остаётся формулировкой варианта «по задачам» —
   порталы, настроившие её до появления вариантов, не должны её потерять.
"""

from datetime import datetime
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from .billing_crm_service import BillingCrmService
from .billing_line_template import (
    DEFAULT_LINE_TEMPLATES,
    DEFAULT_LINE_VARIANT,
    DEFAULT_SERVICE_NAME,
    LINE_VARIANTS,
    default_line_template,
    normalize_line_template,
    normalize_line_variant,
    normalize_service_name,
    render_line_template,
)
from .billing_service import (
    GROUPING_FROM_REQUEST,
    GROUPING_FROM_SETTINGS,
    LINE_TITLE_SINGLE,
    BillingFilter,
    BillingService,
)
from .billing_settings import load_billing_settings
from .models import (
    Bitrix24Account,
    PortalTask,
    PortalUser,
    ProjectCard,
    TimesheetItem,
)


def settings(**overrides):
    """Настройки портала для сервиса. По умолчанию — как из коробки."""
    base = {
        "allow_open_period": True,
        "accountants": [],
        "act_template_id": 0,
        "line_variant": DEFAULT_LINE_VARIANT,
        "task_level": "task",
    }
    base.update(overrides)
    return base


class VariantNormalizationTest(TestCase):
    """Чистые функции: вариант, формулировка по умолчанию, услуга."""

    def test_four_variants_and_no_more(self):
        self.assertEqual(LINE_VARIANTS, ("task", "project", "employee", "single"))

    def test_unknown_variant_reads_as_by_task(self):
        """Опечатка в настройке не имеет права свернуть счёт в одну строку."""
        self.assertEqual(normalize_line_variant("одной-строкой"), "task")
        self.assertEqual(normalize_line_variant(""), "task")
        self.assertEqual(normalize_line_variant(None), "task")
        self.assertEqual(normalize_line_variant(" SINGLE "), "single")

    def test_every_variant_has_its_own_default_wording(self):
        wordings = {variant: default_line_template(variant) for variant in LINE_VARIANTS}

        self.assertEqual(wordings, {
            "task": "{задача}, {месяц}",
            "project": "{услуга} по проекту „{проект}“, {месяц}",
            "employee": "Работы {сотрудник}, {месяц}",
            "single": "Услуги по разработке и сопровождению за {месяц}",
        })
        # Ни одна формулировка не повторяет другую: смысл вариантов в том,
        # что строка читается по-разному.
        self.assertEqual(len(set(wordings.values())), len(LINE_VARIANTS))

    def test_empty_wording_means_the_default_of_that_variant(self):
        """Пустая настройка — «как по умолчанию ЭТОГО варианта».

        Иначе счёт на одну строку получил бы «{задача}, {месяц}» и прочитался
        как «Услуги по договору, август 2026».
        """
        for variant in LINE_VARIANTS:
            self.assertEqual(
                normalize_line_template("", variant), DEFAULT_LINE_TEMPLATES[variant],
            )
        self.assertEqual(normalize_line_template("  {задача}  ", "single"), "{задача}")

    def test_service_name_falls_back_to_a_word_not_to_emptiness(self):
        """«по проекту „Личный кабинет“» без подлежащего выглядит обрезанным."""
        self.assertEqual(normalize_service_name(""), DEFAULT_SERVICE_NAME)
        self.assertEqual(normalize_service_name(None), "Разработка")
        self.assertEqual(normalize_service_name("  Сопровождение "), "Сопровождение")

    def test_employee_and_service_placeholders_are_substituted(self):
        text = render_line_template(
            "Работы {сотрудник} ({услуга}), {месяц}",
            {"сотрудник": "Петровой Анны", "услуга": "Аналитика", "месяц": "август 2026"},
        )

        self.assertEqual(text, "Работы Петровой Анны (Аналитика), август 2026")

    def test_known_placeholder_not_passed_at_all_is_still_known(self):
        """Не переданная ``{сотрудник}`` не уходит в счёт скобками.

        Раньше известными считались только переданные ключи, и шаблон
        варианта «по сотрудникам», применённый там, где сотрудник один не
        определён, напечатал бы «Работы {сотрудник}».
        """
        text = render_line_template("Работы {сотрудник}, {месяц}", {"месяц": "август 2026"})

        self.assertEqual(text, "Работы август 2026")

    def test_unknown_placeholder_is_still_visible(self):
        """Решение прежнее и не меняется: опечатку видно в предпросмотре."""
        text = render_line_template("{задача} — {задание}", {"задача": "Правки"})

        self.assertEqual(text, "Правки — {задание}")


class VariantFixture(TestCase):
    """Портал, два проекта одного клиента, две задачи, два сотрудника."""

    def setUp(self):
        self.account = Bitrix24Account.objects.create(
            b24_user_id=11, is_b24_user_admin=True, member_id="m-variants",
            is_master_account=True, domain_url="variants.bitrix24.ru",
            status="active", application_version=1,
        )
        PortalUser.objects.create(
            bitrix24_account=self.account, bitrix_id="11",
            name="Егор", last_name="Цыганков",
        )
        PortalUser.objects.create(
            bitrix24_account=self.account, bitrix_id="12",
            name="Анна", last_name="Петрова",
        )
        for project_id, project_name in (("73", "Личный кабинет"), ("88", "Внедрение CRM")):
            ProjectCard.objects.create(
                bitrix24_account=self.account, project_id=project_id,
                project_name=project_name, stage="in_work", hourly_rate=2000.0,
                company_id="15", company_name="ООО НУОЛАБ",
                our_legal_entity_id="7", our_legal_entity_name="ООО Майнсофт",
            )
        PortalTask.objects.create(
            bitrix24_account=self.account, bitrix_id="100",
            title="Настройка отчётов", group_id="73",
        )
        PortalTask.objects.create(
            bitrix24_account=self.account, bitrix_id="200",
            title="Обучение", group_id="88",
        )

    def entry(self, bitrix_id, *, task_id, project_id, project_title,
              employee_id="11", hours=2.0, rate=2000.0, day=15):
        return TimesheetItem.objects.create(
            bitrix24_account=self.account, bitrix_id=bitrix_id, task_id=task_id,
            employee_id=employee_id, hours=hours, is_billable=True,
            project_id=project_id, project_title=project_title,
            hourly_rate_snapshot=rate, description="работа",
            task_hierarchy_ids=[task_id] if task_id else [],
            task_hierarchy_titles=[""] if task_id else [],
            date_reflection=timezone.make_aware(datetime(2026, 8, day, 0, 0)),
        )

    def service(self, **overrides):
        return BillingService(self.account, client=object(), settings=settings(**overrides))

    def filters(self, **kwargs):
        payload = {"date_from": "2026-08-01", "date_to": "2026-08-31", "company_id": "15"}
        payload.update(kwargs)
        return BillingFilter.from_payload(payload)


class FourVariantsFixture(VariantFixture):
    """Четыре часа в двух проектах, двух задачах, у двух людей.

    Такой набор специально «пересекающийся»: при любом варианте строк
    получается больше одной, и подмена варианта видна и по составу, и по
    формулировке.
    """

    def setUp(self):
        super().setUp()
        self.entry(1, task_id="100", project_id="73", project_title="Личный кабинет",
                   employee_id="11", hours=2.0)
        self.entry(2, task_id="200", project_id="88", project_title="Внедрение CRM",
                   employee_id="12", hours=3.0)

    def collect(self, variant, **overrides):
        service = self.service(**overrides)
        return service.collect(self.filters(grouping=variant))


class VariantLinesTest(FourVariantsFixture):
    def test_by_task_gives_a_line_per_task(self):
        selection = self.collect("task")

        self.assertEqual(
            sorted((line["subject"], line["hours"]) for line in selection.lines),
            [("Настройка отчётов", 2.0), ("Обучение", 3.0)],
        )
        self.assertEqual(
            sorted(line["title"] for line in selection.lines),
            ["Настройка отчётов, август 2026", "Обучение, август 2026"],
        )

    def test_by_project_gives_a_line_per_project(self):
        selection = self.collect("project")

        self.assertEqual(
            sorted(line["title"] for line in selection.lines),
            [
                "Разработка по проекту „Внедрение CRM“, август 2026",
                "Разработка по проекту „Личный кабинет“, август 2026",
            ],
        )

    def test_by_employee_gives_a_line_per_person(self):
        selection = self.collect("employee")

        self.assertEqual(
            sorted(line["title"] for line in selection.lines),
            ["Работы Петрова Анна, август 2026", "Работы Цыганков Егор, август 2026"],
        )

    def test_single_gives_exactly_one_line_about_services(self):
        selection = self.collect("single")

        self.assertEqual(len(selection.lines), 1)
        self.assertEqual(selection.lines[0]["subject"], LINE_TITLE_SINGLE)
        self.assertEqual(
            selection.lines[0]["title"],
            "Услуги по разработке и сопровождению за август 2026",
        )
        self.assertEqual(selection.lines[0]["hours"], 5.0)

    def test_the_total_does_not_depend_on_the_variant(self):
        """Вариант — про читаемость счёта, а не про деньги.

        Это главная защита фичи: если сумма поедет от переключения варианта,
        человек в мастере обнаружит это уже после разговора с клиентом.
        """
        totals = {}
        for variant in LINE_VARIANTS:
            selection = self.collect(variant)
            totals[variant] = (
                selection.total_hours, selection.total_amount, len(selection.entries),
            )

        self.assertEqual(len(set(totals.values())), 1, totals)
        self.assertEqual(set(totals.values()), {(5.0, 10000.0, 2)})

    def test_each_variant_uses_its_own_wording_and_not_a_neighbours(self):
        """Формулировки не перетекают между вариантами."""
        titles = {
            variant: " | ".join(sorted(line["title"] for line in self.collect(variant).lines))
            for variant in LINE_VARIANTS
        }

        self.assertNotIn("по проекту", titles["task"])
        self.assertNotIn("Работы", titles["project"])
        self.assertNotIn("по проекту", titles["employee"])
        self.assertNotIn("Услуги по разработке", titles["task"])
        self.assertEqual(len(set(titles.values())), len(LINE_VARIANTS))


class VariantWordingSettingsTest(FourVariantsFixture):
    def test_portal_wording_overrides_the_default_of_one_variant_only(self):
        """Своя формулировка у варианта не задевает остальные три."""
        overrides = {
            "line_templates": {"single": "Услуги по договору за {период}"},
        }

        self.assertEqual(
            self.collect("single", **overrides).lines[0]["title"],
            "Услуги по договору за 01.08.2026—31.08.2026",
        )
        self.assertEqual(
            sorted(line["title"] for line in self.collect("task", **overrides).lines),
            ["Настройка отчётов, август 2026", "Обучение, август 2026"],
        )

    def test_service_name_setting_reaches_the_project_wording(self):
        selection = self.collect("project", service_name="Сопровождение")

        self.assertEqual(
            sorted(line["title"] for line in selection.lines),
            [
                "Сопровождение по проекту „Внедрение CRM“, август 2026",
                "Сопровождение по проекту „Личный кабинет“, август 2026",
            ],
        )

    def test_employee_placeholder_works_in_any_variant(self):
        """«{сотрудник}» — про строку, а не про вариант.

        В строке на задачу, которую вёл один человек, его имя в наименовании
        работ — законная формулировка, и требовать для неё варианта «по
        сотрудникам» незачем.
        """
        selection = self.collect(
            "task", line_templates={"task": "{задача} ({сотрудник}), {месяц}"},
        )

        self.assertEqual(
            sorted(line["title"] for line in selection.lines),
            [
                "Настройка отчётов (Цыганков Егор), август 2026",
                "Обучение (Петрова Анна), август 2026",
            ],
        )

    def test_legacy_single_key_still_is_the_task_wording(self):
        """Портал, настроивший формулировку до вариантов, её не теряет."""
        selection = self.collect("task", line_template="{задача} за {период}")

        self.assertEqual(
            sorted(line["title"] for line in selection.lines),
            ["Настройка отчётов за 01.08.2026—31.08.2026", "Обучение за 01.08.2026—31.08.2026"],
        )


class SharedFieldsTest(VariantFixture):
    """Проект и сотрудник строки — только общие, иначе пусто."""

    def setUp(self):
        super().setUp()
        # Одна задача, но часы в двух проектах и у двух людей: строка «по
        # задаче» собирает их вместе.
        self.entry(1, task_id="100", project_id="73", project_title="Личный кабинет",
                   employee_id="11", hours=2.0)
        self.entry(2, task_id="100", project_id="88", project_title="Внедрение CRM",
                   employee_id="12", hours=3.0)

    def test_line_of_several_projects_has_no_project(self):
        """Раньше брался первый попавшийся — и «{проект}» врал в счёте."""
        selection = self.service().collect(self.filters(grouping="task"))

        self.assertEqual(len(selection.lines), 1)
        self.assertEqual(selection.lines[0]["project_id"], "")
        self.assertEqual(selection.lines[0]["project_name"], "")

    def test_project_placeholder_empties_out_with_its_separator(self):
        selection = self.service(
            line_templates={"task": "{задача} ({проект}), {месяц}"},
        ).collect(self.filters(grouping="task"))

        self.assertEqual(selection.lines[0]["title"], "Настройка отчётов, август 2026")

    def test_employee_placeholder_empties_out_when_there_are_several(self):
        selection = self.service(
            line_templates={"task": "{задача} — {сотрудник}"},
        ).collect(self.filters(grouping="task"))

        self.assertEqual(selection.lines[0]["title"], "Настройка отчётов")

    def test_single_line_over_two_projects_keeps_no_project_either(self):
        selection = self.service().collect(self.filters(grouping="single"))

        self.assertEqual(selection.lines[0]["project_id"], "")
        self.assertEqual(selection.lines[0]["hours"], 5.0)


class VariantSourceTest(FourVariantsFixture):
    """Откуда взялся вариант: настройка портала или выбор в мастере."""

    def test_portal_setting_is_the_wizard_default(self):
        """То, чего просили: «по задачам» больше не зашито в код."""
        service = self.service(line_variant="single")
        filters = service.build_filter({"date_from": "2026-08-01", "date_to": "2026-08-31"})

        self.assertEqual(filters.grouping, "single")
        self.assertEqual(filters.grouping_source, GROUPING_FROM_SETTINGS)

    def test_request_beats_the_setting(self):
        service = self.service(line_variant="single")
        filters = service.build_filter({"grouping": "employee"})

        self.assertEqual(filters.grouping, "employee")
        self.assertEqual(filters.grouping_source, GROUPING_FROM_REQUEST)

    def test_broken_setting_reads_as_by_task_and_does_not_raise(self):
        """Негодная настройка не роняет предпросмотр и не свёртывает счёт."""
        service = self.service(line_variant="как-нибудь")
        filters = service.build_filter({})

        self.assertEqual(filters.grouping, "task")
        self.assertEqual(filters.grouping_source, GROUPING_FROM_SETTINGS)

    def test_unknown_grouping_in_the_request_is_still_an_error(self):
        """Чужое значение ОТ КЛИЕНТА — ошибка, а не молчаливая подмена."""
        from .billing_service import BillingError

        with self.assertRaises(BillingError) as ctx:
            self.service().build_filter({"grouping": "по-настроению"})

        self.assertEqual(ctx.exception.code, "bad_grouping")

    def test_preview_payload_carries_the_variant_and_its_source(self):
        service = self.service(line_variant="project")
        payload = service.collect(service.build_filter({
            "date_from": "2026-08-01", "date_to": "2026-08-31", "company_id": "15",
        })).as_payload()

        self.assertEqual(payload["grouping"], "project")
        self.assertEqual(payload["grouping_source"], GROUPING_FROM_SETTINGS)

    def test_source_is_kept_in_the_filter_snapshot(self):
        service = self.service(line_variant="single")
        filters = service.build_filter({
            "date_from": "2026-08-01", "date_to": "2026-08-31", "company_id": "15",
        })

        self.assertEqual(filters.as_snapshot()["grouping"], "single")
        self.assertEqual(filters.as_snapshot()["grouping_source"], GROUPING_FROM_SETTINGS)


class VariantReachesCrmTest(FourVariantsFixture):
    """Товарные строки счёта повторяют строки документа при любом варианте."""

    def issue(self, variant):
        service = self.service(line_variant=variant)
        filters = service.build_filter({
            "date_from": "2026-08-01", "date_to": "2026-08-31", "company_id": "15",
        })
        selection = service.collect(filters)
        document = service.create_document(
            selection, filters, created_by_id="11", created_by_name="Цыганков Егор",
        )
        rows = BillingCrmService(
            self.account, client=object(), service=service,
        ).build_product_rows(document)
        return document, rows

    def test_product_rows_repeat_the_lines_of_every_variant(self):
        for variant in LINE_VARIANTS:
            with self.subTest(variant=variant):
                document, rows = self.issue(variant)

                self.assertEqual(
                    [row["productName"] for row in rows],
                    [line.title for line in document.lines.all()],
                )
                self.assertEqual(document.grouping, variant)
                self.assertEqual(document.filter_snapshot["grouping"], variant)
                self.assertEqual(document.total_amount, 10000.0)
                # Детализация — иерархия «задача → сотрудник → списание» и от
                # варианта строк не зависит: списания в снимке все.
                self.assertEqual(document.entries.count(), 2)
                document.delete()

    def test_single_variant_product_row_is_one_and_names_the_services(self):
        document, rows = self.issue("single")

        self.assertEqual(len(rows), 1)
        self.assertEqual(
            rows[0]["productName"], "Услуги по разработке и сопровождению за август 2026",
        )


class BillingSettingsReadTest(TestCase):
    """Разбор настроек вариантов из конфигурации приложения."""

    def setUp(self):
        self.account = Bitrix24Account.objects.create(
            b24_user_id=11, is_b24_user_admin=True, member_id="m-variant-settings",
            is_master_account=True, domain_url="variant-settings.bitrix24.ru",
            status="active", application_version=1,
        )

    def load(self, config):
        with patch(
            "main.configuration_service.ConfigurationService.get_configuration_sync",
            return_value=config,
        ):
            return load_billing_settings(self.account, client=object())

    def test_defaults_when_nothing_is_configured(self):
        loaded = self.load({})

        self.assertEqual(loaded["line_variant"], "task")
        self.assertEqual(loaded["service_name"], DEFAULT_SERVICE_NAME)
        self.assertEqual(loaded["line_templates"], DEFAULT_LINE_TEMPLATES)

    def test_variant_and_wordings_are_read_from_the_configuration(self):
        loaded = self.load({
            "billing_line_variant": "single",
            "billing_line_template": "{задача} за {месяц}",
            "billing_line_template_project": "{услуга}: {проект}",
            "billing_line_template_employee": "{сотрудник}",
            "billing_line_template_single": "Услуги за {месяц}",
            "billing_service_name": "Сопровождение",
        })

        self.assertEqual(loaded["line_variant"], "single")
        self.assertEqual(loaded["service_name"], "Сопровождение")
        self.assertEqual(loaded["line_templates"], {
            "task": "{задача} за {месяц}",
            "project": "{услуга}: {проект}",
            "employee": "{сотрудник}",
            "single": "Услуги за {месяц}",
        })
        # Одиночный ключ остаётся формулировкой варианта «по задачам».
        self.assertEqual(loaded["line_template"], "{задача} за {месяц}")

    def test_missing_wording_of_one_variant_falls_back_to_its_own_default(self):
        loaded = self.load({"billing_line_template_single": "Услуги за {месяц}"})

        self.assertEqual(loaded["line_templates"]["single"], "Услуги за {месяц}")
        self.assertEqual(
            loaded["line_templates"]["project"], DEFAULT_LINE_TEMPLATES["project"],
        )

    def test_unreadable_configuration_gives_defaults_not_emptiness(self):
        """Недоступный портал не оставляет строки счёта без наименования."""
        with patch(
            "main.configuration_service.ConfigurationService.get_configuration_sync",
            side_effect=RuntimeError("портал молчит"),
        ):
            loaded = load_billing_settings(self.account, client=object())

        self.assertEqual(loaded["line_variant"], "task")
        self.assertEqual(loaded["line_templates"], DEFAULT_LINE_TEMPLATES)
        self.assertEqual(loaded["service_name"], DEFAULT_SERVICE_NAME)
