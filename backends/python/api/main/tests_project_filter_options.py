"""Фильтр «Проекты» в отчётах: опции — из реестра карточек, а не из строк списаний.

Боевой дефект 06.08.2026 (жалоба клиента): проект есть в рабочем пространстве,
в выпадашке фильтра отчёта его нет — «Ничего не найдено». Причина: опции
собирались обходом timesheet_item, а реестр карточек работал только отсечкой,
и активная карточка без подходящих строк списаний не попадала в список никогда.

Тесты закрывают обе половины пути: сборку опций и применение выбранной опции
к строкам списаний. Раньше на эту функцию не было ни одного теста.
"""
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from .models import Bitrix24Account, ProjectCard, TimesheetItem
from .report_queries import build_filtered_timesheet_queryset, build_project_filter_options


class _ProjectFilterTestBase(TestCase):
    def setUp(self):
        cache.clear()
        self.account = Bitrix24Account.objects.create(
            b24_user_id=1,
            is_b24_user_admin=True,
            member_id="m-filter-options-1",
            is_master_account=True,
            domain_url="example.bitrix24.ru",
            status="active",
            application_version=1,
        )
        self._next_bitrix_id = 0

    def _card(self, **kwargs):
        defaults = {
            "bitrix24_account": self.account,
            "stage": "Новый",
            "manual_stage": "Новый",
        }
        defaults.update(kwargs)
        return ProjectCard.objects.create(**defaults)

    def _timesheet(self, **kwargs):
        self._next_bitrix_id += 1
        defaults = {
            "bitrix24_account": self.account,
            "bitrix_id": self._next_bitrix_id,
            "task_id": str(self._next_bitrix_id),
            "employee_id": "emp-1",
            "hours": 1.0,
            "date_reflection": timezone.now(),
        }
        defaults.update(kwargs)
        return TimesheetItem.objects.create(**defaults)


class ProjectFilterOptionsTest(_ProjectFilterTestBase):
    def test_active_card_without_timesheets_is_offered(self):
        """Ровно случай из жалобы: проект только что создан, списаний под него
        в локальной базе ещё нет. В рабочем пространстве он есть, значит и в
        фильтре обязан быть."""
        self._card(project_id="425", project_name="ВСС")

        self.assertEqual(
            build_project_filter_options(self.account),
            [{"id": "425", "name": "ВСС"}],
        )

    def test_card_linked_to_timesheets_only_by_project_item_id_is_offered(self):
        """Списания привязаны к карточке через элемент смарт-процесса: ни
        project_id, ни project_title с карточкой не совпадают. Доска такую
        связь видит (refresh_writeoff_stats), сборщик опций не видел."""
        self._card(project_id="425", project_item_id="9001", project_name="ВСС")
        self._timesheet(project_item_id="9001", project_id="", project_title="Поддержка ВСС 2026")

        self.assertEqual(
            build_project_filter_options(self.account),
            [{"id": "425", "name": "ВСС"}],
        )

    def test_option_is_labelled_with_card_name_not_timesheet_title(self):
        """Тело отчёта показывает имя карточки (resolve_project_name_for_row),
        значит и опция обязана называться так же — иначе человек ищет имя,
        которое видит везде, и не находит."""
        self._card(project_id="425", project_name="ВСС")
        self._timesheet(project_id="425", project_title="Старое название группы")

        self.assertEqual(
            build_project_filter_options(self.account),
            [{"id": "425", "name": "ВСС"}],
        )

    def test_archived_card_is_not_offered(self):
        self._card(project_id="425", project_name="ВСС", is_archived=True)
        self._timesheet(project_id="425", project_title="ВСС")

        self.assertEqual(build_project_filter_options(self.account), [])

    def test_falls_back_to_timesheets_when_registry_is_empty(self):
        """Реестр пуст (свежая установка либо таблица карточек недоступна) —
        фильтр не имеет права остаться пустым, это было бы хуже сегодняшнего."""
        self._timesheet(project_id="777", project_title="Проект без карточки")

        self.assertEqual(
            build_project_filter_options(self.account),
            [{"id": "777", "name": "Проект без карточки"}],
        )

    def test_options_are_sorted_by_name(self):
        self._card(project_id="1", project_name="Яблоко")
        self._card(project_id="2", project_name="Астра")

        self.assertEqual(
            [option["name"] for option in build_project_filter_options(self.account)],
            ["Астра", "Яблоко"],
        )

    def test_other_accounts_projects_are_not_offered(self):
        other = Bitrix24Account.objects.create(
            b24_user_id=2,
            is_b24_user_admin=True,
            member_id="m-filter-options-2",
            is_master_account=True,
            domain_url="other.bitrix24.ru",
            status="active",
            application_version=1,
        )
        ProjectCard.objects.create(
            bitrix24_account=other,
            project_id="425",
            project_name="Чужой проект",
            stage="Новый",
            manual_stage="Новый",
        )

        self.assertEqual(build_project_filter_options(self.account), [])


class ProjectFilterSelectionTest(_ProjectFilterTestBase):
    def test_selected_card_matches_rows_linked_by_project_item_id(self):
        """Опция несёт один id (id группы), а строки могут быть привязаны
        другим ключом. Выбор проекта обязан разворачиваться в полный набор
        ключей карточки, иначе отчёт вернётся пустым."""
        self._card(project_id="425", project_item_id="9001", project_name="ВСС")
        row = self._timesheet(project_item_id="9001", project_id="", project_title="Поддержка ВСС 2026")

        queryset = build_filtered_timesheet_queryset(self.account, {"project_ids": ["425"]})

        self.assertEqual([item.bitrix_id for item in queryset], [row.bitrix_id])

    def test_selected_card_matches_rows_linked_by_title(self):
        self._card(project_id="425", project_item_id="9001", project_name="ВСС")
        row = self._timesheet(project_item_id="", project_id="", project_title="ВСС")

        queryset = build_filtered_timesheet_queryset(self.account, {"project_ids": ["425"]})

        self.assertEqual([item.bitrix_id for item in queryset], [row.bitrix_id])

    def test_group_id_does_not_leak_into_project_item_id_match(self):
        """Коллизия пространств идентификаторов: id группы одного проекта
        совпадает с id элемента смарт-процесса другого. Выбор первого не имеет
        права затащить в отчёт строки второго."""
        self._card(project_id="425", project_item_id="9001", project_name="Наш проект")
        self._card(project_id="808", project_item_id="425", project_name="Чужой проект")
        ours = self._timesheet(project_item_id="9001", project_id="425", project_title="Наш проект")
        self._timesheet(project_item_id="425", project_id="808", project_title="Чужой проект")

        queryset = build_filtered_timesheet_queryset(self.account, {"project_ids": ["425"]})

        self.assertEqual([item.bitrix_id for item in queryset], [ours.bitrix_id])

    def test_exclude_mode_drops_every_key_of_the_selected_card(self):
        self._card(project_id="425", project_item_id="9001", project_name="ВСС")
        self._timesheet(project_item_id="9001", project_id="", project_title="Поддержка ВСС 2026")
        kept = self._timesheet(project_item_id="7002", project_id="808", project_title="Другой проект")

        queryset = build_filtered_timesheet_queryset(
            self.account, {"project_ids": ["425"], "project_mode": "exclude"}
        )

        self.assertEqual([item.bitrix_id for item in queryset], [kept.bitrix_id])

    def test_selection_without_card_still_matches_by_raw_value(self):
        """Реестр пуст — опции пришли из списаний, и выбранное значение
        по-прежнему обязано матчиться напрямую."""
        row = self._timesheet(project_id="777", project_title="Проект без карточки")

        queryset = build_filtered_timesheet_queryset(self.account, {"project_ids": ["777"]})

        self.assertEqual([item.bitrix_id for item in queryset], [row.bitrix_id])
