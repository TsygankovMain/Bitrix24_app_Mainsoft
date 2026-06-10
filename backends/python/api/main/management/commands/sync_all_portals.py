"""Management command: sync_all_portals

Фоновая инкрементальная синхронизация трудозатрат по всем настроенным
порталам. Запускается внешним планировщиком платформы (cron Timeweb).

Usage:
    python manage.py sync_all_portals
    python manage.py sync_all_portals --days 3
"""
from django.core.management.base import BaseCommand

from main.sync_scheduler_service import run_scheduled_sync, DEFAULT_WINDOW_DAYS


class Command(BaseCommand):
    help = "Инкрементальный фоновый синк трудозатрат по всем настроенным порталам."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=DEFAULT_WINDOW_DAYS,
            help=f"Окно инкремента в днях (по умолчанию {DEFAULT_WINDOW_DAYS}).",
        )

    def handle(self, *args, **options):
        days = options["days"]
        run = run_scheduled_sync(days=days)
        self.stdout.write(
            f"Scheduled sync done: status={run.status}, "
            f"portals {run.portals_synced}/{run.portals_total}, "
            f"items={run.items_synced}, window={run.window_days}d."
        )
