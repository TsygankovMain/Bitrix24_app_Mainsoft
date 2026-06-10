"""Management command: dedupe_portal_data

Этап 2 перестройки мультитенантности: схлопывает дубли TimesheetItem/ProjectCard
в пределах Portal (оставляет мастер-копию, иначе свежайшую). По умолчанию
DRY-RUN — только отчёт, без удаления. Реальное удаление — только с --apply.

Запускать ПОСЛЕ backfill_portal_links (4.1) и ДО этапа 4 (включение portal-
уникальности). Сначала прогнать БЕЗ --apply, проверить отчёт, затем --apply.

Usage:
    python manage.py dedupe_portal_data            # dry-run (отчёт)
    python manage.py dedupe_portal_data --apply    # реальное удаление дублей
"""
from django.core.management.base import BaseCommand

from main.portal_dedupe_service import dedupe_portal_data


class Command(BaseCommand):
    help = "Дедуп TimesheetItem/ProjectCard в пределах Portal (dry-run по умолчанию)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply", action="store_true",
            help="Выполнить реальное удаление дублей (по умолчанию только отчёт).",
        )

    def handle(self, *args, **options):
        apply = options["apply"]
        report = dedupe_portal_data(apply=apply)

        if report["backfill_incomplete"]:
            self.stdout.write(self.style.ERROR(
                "Backfill не завершён (есть записи с пустым portal у аккаунтов с portal). "
                "Сначала добейте `backfill_portal_links`. Дедуп НЕ применён."
            ))
            return

        mode = "ПРИМЕНЕНО" if report["applied"] else "DRY-RUN (ничего не удалено)"
        self.stdout.write(f"Дедуп [{mode}]:")
        self.stdout.write(
            f"  TimesheetItem: групп-дублей={report['timesheets']['duplicate_groups']}, "
            f"к удалению={report['timesheets']['rows_to_delete']}"
        )
        self.stdout.write(
            f"  ProjectCard:   групп-дублей={report['cards']['duplicate_groups']}, "
            f"к удалению={report['cards']['rows_to_delete']}"
        )
        if not report["applied"]:
            self.stdout.write(self.style.WARNING(
                "Это был dry-run. Для реального удаления запустите с --apply "
                "(только после проверки отчёта и на копии прода — см. план, Часть B)."
            ))
