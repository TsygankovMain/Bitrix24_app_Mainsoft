"""Строки счёта по задачам: названия, подзадачи, часы без задачи, шаблон.

Зачем этот файл. В счёт клиенту НУОЛАБ ушло наименование работ «НУОЛАБ» —
имя карточки проекта, названной по клиенту. Описания работ в документе не
оказалось вовсе. Здесь закрепляется исправление: строки собираются по
задачам, в наименовании работ стоит НАЗВАНИЕ задачи, а как именно оно
читается — решает шаблон портала.

Четыре вещи, которые обязаны держаться:

1. название задачи в строке приходит из справочника задач, а при его
   отсутствии — из снимка иерархии самой записи, и никогда не подменяется
   идентификатором, если название вообще есть;
2. часы без задачи не теряются и не приписываются чужой задаче — у них своя
   строка;
3. подзадачи собираются по выбранному настройкой уровню, и переключение
   уровня меняет ТОЛЬКО состав строк, а не сумму документа;
4. текст, утверждённый человеком в предпросмотре, доходит и до строки
   документа, и до товарной строки счёта в CRM — без него правка оставалась
   бы на экране.
"""

from datetime import date, datetime

from django.test import TestCase
from django.utils import timezone

from .billing_crm_service import BillingCrmService
from .billing_line_template import (
    DEFAULT_LINE_TEMPLATE,
    TASK_LEVEL_ROOT,
    TASK_LEVEL_TASK,
    month_label,
    normalize_line_template,
    period_label,
    render_line_template,
)
from .billing_service import (
    LINE_TITLE_NO_TASK,
    BillingFilter,
    BillingService,
)
from .models import (
    BillingDocument,
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
        "line_template": DEFAULT_LINE_TEMPLATE,
        "task_level": TASK_LEVEL_TASK,
    }
    base.update(overrides)
    return base


class LineTemplateTest(TestCase):
    """Чистые функции шаблона. Ни базы, ни портала."""

    def test_default_template_reads_as_task_and_month(self):
        text = render_line_template(
            DEFAULT_LINE_TEMPLATE,
            {"задача": "Настройка отчётов", "месяц": "август 2026"},
        )

        self.assertEqual(text, "Настройка отчётов, август 2026")

    def test_all_five_placeholders_are_substituted(self):
        text = render_line_template(
            "{задача} · {проект} · {клиент} · {месяц} · {период}",
            {
                "задача": "Настройка отчётов",
                "проект": "Мейнсофт",
                "клиент": "НУОЛАБ",
                "месяц": "август 2026",
                "период": "01.08.2026—31.08.2026",
            },
        )

        self.assertEqual(
            text,
            "Настройка отчётов · Мейнсофт · НУОЛАБ · август 2026 · 01.08.2026—31.08.2026",
        )

    def test_unknown_placeholder_stays_visible(self):
        """Опечатку в настройке видно в предпросмотре, а не у клиента.

        Стереть неизвестную подстановку значило бы отдать правильно
        выглядящую строку с пропавшим куском формулировки.
        """
        text = render_line_template("{задача} — {задание}", {"задача": "Правки"})

        self.assertEqual(text, "Правки — {задание}")

    def test_known_placeholder_without_value_takes_its_separator_along(self):
        self.assertEqual(
            render_line_template("{задача}, {месяц}", {"задача": "Правки", "месяц": ""}),
            "Правки",
        )
        self.assertEqual(
            render_line_template(
                "{задача} ({проект}), {месяц}",
                {"задача": "Правки", "проект": "", "месяц": "август 2026"},
            ),
            "Правки, август 2026",
        )

    def test_empty_result_falls_back_to_the_subject(self):
        """Пустое наименование работ не уходит в счёт ни при какой настройке."""
        self.assertEqual(
            render_line_template("{клиент}", {"клиент": ""}, fallback="Настройка отчётов"),
            "Настройка отчётов",
        )

    def test_empty_setting_means_default_template(self):
        self.assertEqual(normalize_line_template(""), DEFAULT_LINE_TEMPLATE)
        self.assertEqual(normalize_line_template(None), DEFAULT_LINE_TEMPLATE)
        self.assertEqual(normalize_line_template("  {задача}  "), "{задача}")

    def test_month_label_covers_one_month_and_a_span(self):
        self.assertEqual(month_label(date(2026, 8, 1), date(2026, 8, 31)), "август 2026")
        self.assertEqual(
            month_label(date(2026, 8, 1), date(2026, 9, 30)), "август—сентябрь 2026",
        )
        # Год начала работ соврать нельзя: указываются оба.
        self.assertEqual(
            month_label(date(2026, 12, 1), date(2027, 1, 31)),
            "декабрь 2026 — январь 2027",
        )
        self.assertEqual(month_label(None, None), "")

    def test_period_label_is_two_dates(self):
        self.assertEqual(
            period_label(date(2026, 8, 1), date(2026, 8, 31)), "01.08.2026—31.08.2026",
        )
        self.assertEqual(period_label(date(2026, 8, 1), date(2026, 8, 1)), "01.08.2026")


class TaskLineFixture(TestCase):
    """Портал, проект одного клиента, дерево задач и списания в нём."""

    def setUp(self):
        self.account = Bitrix24Account.objects.create(
            b24_user_id=11, is_b24_user_admin=True, member_id="m-task-lines",
            is_master_account=True, domain_url="task-lines.bitrix24.ru",
            status="active", application_version=1,
        )
        PortalUser.objects.create(
            bitrix24_account=self.account, bitrix_id="11",
            name="Егор", last_name="Цыганков",
        )
        ProjectCard.objects.create(
            bitrix24_account=self.account, project_id="73", project_name="НУОЛАБ",
            stage="in_work", hourly_rate=2000.0,
            company_id="15", company_name="ООО НУОЛАБ",
            our_legal_entity_id="7", our_legal_entity_name="ООО Майнсофт",
        )

    def portal_task(self, task_id, title, *, group_id="73"):
        return PortalTask.objects.create(
            bitrix24_account=self.account, bitrix_id=task_id, title=title,
            group_id=group_id,
        )

    def entry(self, bitrix_id, *, task_id="100", hierarchy=None, hours=2.0,
              rate=2000.0, day=15):
        """Списание. ``hierarchy`` — [(id, название), ...] от корня к задаче."""
        chain = hierarchy if hierarchy is not None else ([(task_id, "")] if task_id else [])
        return TimesheetItem.objects.create(
            bitrix24_account=self.account, bitrix_id=bitrix_id, task_id=task_id,
            employee_id="11", hours=hours, is_billable=True,
            project_id="73", project_title="НУОЛАБ", hourly_rate_snapshot=rate,
            description="работа",
            task_hierarchy_ids=[str(item[0]) for item in chain],
            task_hierarchy_titles=[item[1] for item in chain],
            date_reflection=timezone.make_aware(datetime(2026, 8, day, 0, 0)),
        )

    def service(self, **overrides):
        return BillingService(self.account, client=object(), settings=settings(**overrides))

    def filters(self, **kwargs):
        payload = {"date_from": "2026-08-01", "date_to": "2026-08-31", "company_id": "15"}
        payload.update(kwargs)
        return BillingFilter.from_payload(payload)


class TaskTitlesTest(TaskLineFixture):
    def test_line_carries_task_title_not_project_name(self):
        """Та самая жалоба: в строке было «НУОЛАБ» — имя карточки проекта."""
        self.portal_task("100", "Настройка отчётов")
        self.entry(1, task_id="100")

        lines = self.service().collect(self.filters()).lines

        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]["subject"], "Настройка отчётов")
        self.assertEqual(lines[0]["title"], "Настройка отчётов, август 2026")
        self.assertNotIn("НУОЛАБ", lines[0]["title"])

    def test_title_falls_back_to_the_snapshot_when_lookup_is_empty(self):
        """Справочник задач наполняется раз в час — снимок спасает строку.

        Иначе новая задача уходила бы в счёт номером «Задача 100» вместо
        описания работ.
        """
        self.entry(1, task_id="100", hierarchy=[("100", "Выгрузка в 1С")])

        lines = self.service().collect(self.filters()).lines

        self.assertEqual(lines[0]["subject"], "Выгрузка в 1С")

    def test_lookup_wins_over_the_snapshot(self):
        """Задачу переименовали — в счёт идёт актуальное название."""
        self.portal_task("100", "Выгрузка в 1С (доработка)")
        self.entry(1, task_id="100", hierarchy=[("100", "Выгрузка в 1С")])

        lines = self.service().collect(self.filters()).lines

        self.assertEqual(lines[0]["subject"], "Выгрузка в 1С (доработка)")

    def test_task_without_any_title_degrades_to_its_number(self):
        """Номер хотя бы указывает на задачу в портале. Пустота — ни на что."""
        self.entry(1, task_id="100", hierarchy=[("100", "")])

        lines = self.service().collect(self.filters()).lines

        self.assertEqual(lines[0]["subject"], "Задача 100")

    def test_different_tasks_give_different_lines(self):
        self.portal_task("100", "Настройка отчётов")
        self.portal_task("200", "Обучение")
        self.entry(1, task_id="100", hours=2.0)
        self.entry(2, task_id="200", hours=3.0)

        lines = self.service().collect(self.filters()).lines

        self.assertEqual(
            {line["subject"]: line["hours"] for line in lines},
            {"Настройка отчётов": 2.0, "Обучение": 3.0},
        )


class EntriesWithoutTaskTest(TaskLineFixture):
    def test_hours_without_a_task_get_their_own_line(self):
        """Часы не теряются и не приписываются чужой задаче."""
        self.portal_task("100", "Настройка отчётов")
        self.entry(1, task_id="100", hours=2.0)
        self.entry(2, task_id="", hierarchy=[], hours=3.0)

        selection = self.service().collect(self.filters())

        titles = {line["subject"]: line["hours"] for line in selection.lines}
        self.assertEqual(titles, {"Настройка отчётов": 2.0, LINE_TITLE_NO_TASK: 3.0})
        # Часы дошли до итога документа целиком.
        self.assertEqual(selection.total_hours, 5.0)
        self.assertEqual(selection.total_amount, 10000.0)

    def test_all_taskless_hours_land_in_one_line(self):
        self.entry(1, task_id="", hierarchy=[], hours=2.0)
        self.entry(2, task_id="", hierarchy=[], hours=3.0)

        lines = self.service().collect(self.filters()).lines

        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]["subject"], LINE_TITLE_NO_TASK)
        self.assertEqual(lines[0]["hours"], 5.0)

    def test_taskless_line_goes_last(self):
        """Остаток не читается как главное, за что выставлен счёт."""
        self.portal_task("100", "Ясная задача")
        self.entry(1, task_id="100")
        self.entry(2, task_id="", hierarchy=[])

        lines = self.service().collect(self.filters()).lines

        self.assertEqual([line["subject"] for line in lines][-1], LINE_TITLE_NO_TASK)


class TaskLevelTest(TaskLineFixture):
    """Подзадачи: строка на саму задачу или на её корневого родителя."""

    def setUp(self):
        super().setUp()
        self.portal_task("10", "Внедрение CRM")
        self.portal_task("100", "Настройка отчётов")
        self.portal_task("200", "Обучение")
        self.entry(1, task_id="100", hierarchy=[("10", "Внедрение CRM"), ("100", "Настройка отчётов")], hours=2.0)
        self.entry(2, task_id="200", hierarchy=[("10", "Внедрение CRM"), ("200", "Обучение")], hours=3.0)

    def test_default_level_is_the_task_itself(self):
        selection = self.service().collect(self.filters())

        self.assertEqual(selection.task_level, TASK_LEVEL_TASK)
        self.assertEqual(
            sorted(line["subject"] for line in selection.lines),
            ["Настройка отчётов", "Обучение"],
        )

    def test_root_level_collapses_subtasks_into_one_line(self):
        selection = self.service(task_level=TASK_LEVEL_ROOT).collect(self.filters())

        self.assertEqual(len(selection.lines), 1)
        self.assertEqual(selection.lines[0]["subject"], "Внедрение CRM")
        self.assertEqual(selection.lines[0]["hours"], 5.0)

    def test_level_changes_lines_but_not_the_total(self):
        """Переключение уровня — про читаемость счёта, а не про деньги."""
        by_task = self.service().collect(self.filters())
        by_root = self.service(task_level=TASK_LEVEL_ROOT).collect(self.filters())

        self.assertEqual(by_task.total_hours, by_root.total_hours)
        self.assertEqual(by_task.total_amount, by_root.total_amount)

    def test_unknown_level_reads_as_the_task_itself(self):
        """Опечатка в настройке не имеет права укрупнять строки счёта."""
        selection = self.service(task_level="по-настроению").collect(self.filters())

        self.assertEqual(selection.task_level, TASK_LEVEL_TASK)
        self.assertEqual(len(selection.lines), 2)


class LineTemplateInSelectionTest(TaskLineFixture):
    def setUp(self):
        super().setUp()
        self.portal_task("100", "Настройка отчётов")
        self.entry(1, task_id="100")

    def test_portal_template_rules_the_wording(self):
        service = self.service(line_template="{задача} ({проект}) за {период}")

        lines = service.collect(self.filters()).lines

        self.assertEqual(
            lines[0]["title"],
            "Настройка отчётов (НУОЛАБ) за 01.08.2026—31.08.2026",
        )

    def test_client_placeholder_takes_the_document_client(self):
        service = self.service(line_template="{задача} для {клиент}")

        lines = service.collect(self.filters()).lines

        self.assertEqual(lines[0]["title"], "Настройка отчётов для ООО НУОЛАБ")

    def test_template_can_be_reduced_to_the_task_name_alone(self):
        """Порталу, которому месяц в строке не нужен, хватает «{задача}»."""
        service = self.service(line_template="{задача}")

        lines = service.collect(self.filters()).lines

        self.assertEqual(lines[0]["title"], "Настройка отчётов")

    def test_empty_template_means_the_default_one(self):
        service = self.service(line_template="")

        lines = service.collect(self.filters()).lines

        self.assertEqual(lines[0]["title"], "Настройка отчётов, август 2026")

    def test_selection_reports_how_lines_were_grouped(self):
        """Мастер обязан подписать таблицу, а не заставлять догадываться."""
        payload = self.service().collect(self.filters()).as_payload()

        self.assertEqual(payload["grouping"], "task")
        self.assertEqual(payload["task_level"], TASK_LEVEL_TASK)


class DocumentAndCrmConsistencyTest(TaskLineFixture):
    """Строка документа, товарная строка счёта и детализация — один текст."""

    def setUp(self):
        super().setUp()
        self.portal_task("100", "Настройка отчётов")
        self.portal_task("200", "Обучение")
        self.entry(1, task_id="100", hours=2.0)
        self.entry(2, task_id="200", hours=3.0)

    def issue(self, service, selection, filters):
        return service.create_document(
            selection, filters, created_by_id="11", created_by_name="Цыганков Егор",
        )

    def test_crm_product_rows_repeat_the_document_lines(self):
        service = self.service()
        filters = self.filters()
        selection = service.collect(filters)

        document = self.issue(service, selection, filters)
        rows = BillingCrmService(self.account, client=object(), service=service).build_product_rows(document)

        self.assertEqual(
            [row["productName"] for row in rows],
            [line.title for line in document.lines.all()],
        )
        self.assertEqual(
            [row["productName"] for row in rows],
            ["Настройка отчётов, август 2026", "Обучение, август 2026"],
        )

    def test_hand_edited_title_reaches_the_document_and_crm(self):
        """Правка в предпросмотре — единственное, что видит человек глазами."""
        service = self.service()
        filters = self.filters()
        selection = service.collect(filters)
        approved = [
            {
                "project_id": line["project_id"],
                "title": "Работы по договору 17/26" if index == 0 else line["title"],
                "hours": line["hours"],
                "rate": line["rate"],
                "amount": line["amount"],
            }
            for index, line in enumerate(selection.lines)
        ]

        document = self.issue(service, service.apply_approved_lines(selection, approved), filters)
        rows = BillingCrmService(self.account, client=object(), service=service).build_product_rows(document)

        self.assertEqual(
            [line.title for line in document.lines.all()],
            ["Работы по договору 17/26", "Обучение, август 2026"],
        )
        self.assertEqual([row["productName"] for row in rows], [line.title for line in document.lines.all()])

    def test_entries_keep_the_task_title_for_the_detail_sheet(self):
        """XLSX-детализация берёт название задачи из снимка списания."""
        service = self.service()
        filters = self.filters()
        document = self.issue(service, service.collect(filters), filters)

        self.assertEqual(
            sorted(entry.task_title for entry in document.entries.all()),
            ["Настройка отчётов", "Обучение"],
        )

    def test_task_level_is_kept_in_the_filter_snapshot(self):
        service = self.service(task_level=TASK_LEVEL_ROOT)
        filters = self.filters()
        document = self.issue(service, service.collect(filters), filters)

        self.assertEqual(document.grouping, "task")
        self.assertEqual(document.filter_snapshot["task_level"], TASK_LEVEL_ROOT)
        self.assertEqual(document.status, BillingDocument.STATUS_ISSUED)
