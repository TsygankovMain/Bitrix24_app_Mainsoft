"""Management command: backfill_portal_links

Этап 1 перестройки мультитенантности: проставляет TimesheetItem.portal /
ProjectCard.portal от их bitrix24_account.portal. Идемпотентно, батчами.
Запускать ПОСЛЕ применения миграций 0014/0015 (seed Portal).

Usage:
    python manage.py backfill_portal_links
    python manage.py backfill_portal_links --batch-size 5000
"""
from django.core.management.base import BaseCommand

from main.portal_backfill_service import backfill_portal_links, DEFAULT_BATCH_SIZE


class Command(BaseCommand):
    help = "Backfill FK portal на TimesheetItem/ProjectCard от их аккаунта (этап 1)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--batch-size", type=int, default=DEFAULT_BATCH_SIZE,
            help=f"Размер батча UPDATE (по умолчанию {DEFAULT_BATCH_SIZE}).",
        )

    def handle(self, *args, **options):
        report = backfill_portal_links(batch_size=options["batch_size"])
        self.stdout.write(
            "Backfill done: "
            f"timesheets linked={report['timesheets_linked']} "
            f"unlinked={report['timesheets_unlinked']}; "
            f"cards linked={report['cards_linked']} "
            f"unlinked={report['cards_unlinked']}."
        )
        if report["timesheets_unlinked"] or report["cards_unlinked"]:
            self.stdout.write(self.style.WARNING(
                "Есть записи без portal (аккаунт без member_id/portal). "
                "Проверьте перед дедупом и этапом 4."
            ))
