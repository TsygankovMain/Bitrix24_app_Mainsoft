"""Management command: sync_all_portals

Фоновая синхронизация по всем настроенным порталам. Запускается встроенным
планировщиком приложения (фоновый цикл в start.sh) или вручную.

По расписанию используется --scope project (проекты раз в 3 часа).
Трудозатраты (timesheet) по расписанию НЕ синкаются: дозагрузка происходит
on-demand при открытии отчёта через endpoint timesheet_sync.

Usage:
    python manage.py sync_all_portals --scope project        # встроенный планировщик
    python manage.py sync_all_portals --scope timesheet      # ручной запуск трудозатрат
    python manage.py sync_all_portals                        # default = timesheet (совместимость)
    python manage.py sync_all_portals --days 3 --scope timesheet
"""
from django.core.management.base import BaseCommand

from main.sync_scheduler_service import run_scheduled_sync, DEFAULT_WINDOW_DAYS


class Command(BaseCommand):
    help = (
        "Фоновый синк по всем настроенным порталам. "
        "--scope project: синк проектов (используется встроенным планировщиком, раз в 3 ч). "
        "--scope timesheet: инкрементальный синк трудозатрат (ручной запуск)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=DEFAULT_WINDOW_DAYS,
            help=f"Окно инкремента в днях для scope=timesheet (по умолчанию {DEFAULT_WINDOW_DAYS}).",
        )
        parser.add_argument(
            "--scope",
            type=str,
            default="timesheet",
            choices=["timesheet", "project"],
            help="Что синхронизировать: timesheet (трудозатраты) или project (проекты). "
                 "По умолчанию timesheet (обратная совместимость).",
        )

    def handle(self, *args, **options):
        days = options["days"]
        scope = options["scope"]
        run = run_scheduled_sync(days=days, scope=scope)
        self.stdout.write(
            f"Scheduled sync done: scope={run.scope}, status={run.status}, "
            f"portals {run.portals_synced}/{run.portals_total}, "
            f"items={run.items_synced}, window={run.window_days}d."
        )
