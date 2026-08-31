"""Management command: sync_all_portals

Фоновая синхронизация по всем настроенным порталам. Запускается встроенным
планировщиком приложения (фоновый цикл в start.sh) или вручную.

По расписанию используются все три scope (встроенные фоновые циклы в start.sh):
  - project:   полный синк проектов, раз в 3 часа;
  - timesheet: инкрементальный синк по updatedTime от маркера свежести
    (спека 2026-07-31), каждые 20 минут. Окна по дате отражения больше нет:
    оно не видело записей, внесённых задним числом;
  - timesheet --full: полная ночная сверка, раз в сутки — ТОЛЬКО она ловит
    удаления, которых инкремент не видит в принципе (удалённой записи просто
    нет в выдаче), отключать нельзя;
  - users:     полный синк пользователей (всегда полный, инкремента нет), раз в час.
Дополнительно трудозатраты дозагружаются вручную — кнопкой «Обновить» в
отчёте либо с диагностических страниц — через endpoint timesheet_sync (гейт
по свежести last_timesheet_synced_at). Открытие отчёта синк больше не
триггерит (Фаза 1 sync-offload, задача 4) — данные читаются из БД.

Usage:
    python manage.py sync_all_portals --scope project        # встроенный планировщик (3 ч)
    python manage.py sync_all_portals --scope timesheet      # инкремент (встроенный планировщик, 20 мин)
    python manage.py sync_all_portals --scope timesheet --full  # полная сверка (встроенный планировщик, 1 раз/сутки)
    python manage.py sync_all_portals                        # default = timesheet (совместимость)
    python manage.py sync_all_portals --days 3 --scope timesheet
"""
from django.core.management.base import BaseCommand

from main.sync_scheduler_service import run_scheduled_sync, DEFAULT_WINDOW_DAYS


class Command(BaseCommand):
    help = (
        "Фоновый синк по всем настроенным порталам. "
        "--scope project: синк проектов (используется встроенным планировщиком, раз в 3 ч). "
        "--scope timesheet: инкрементальный синк трудозатрат (встроенный планировщик, каждые 20 мин; "
        "с --full — полная ночная сверка раз в сутки). "
        "--scope users: синк пользователей (всегда полный, встроенный планировщик, раз в час)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=DEFAULT_WINDOW_DAYS,
            help=(
                f"Записывается в журнал SyncRun.window_days (по умолчанию {DEFAULT_WINDOW_DAYS}). "
                "На выборку больше не влияет: инкремент таймшитов ходит по updatedTime "
                "от маркера свежести, а не окном по дате отражения."
            ),
        )
        parser.add_argument(
            "--scope",
            type=str,
            default="timesheet",
            choices=["timesheet", "project", "users", "tasks"],
            help="Что синхронизировать: timesheet (трудозатраты), project (проекты) или "
                 "users (пользователи, раз в ~1 ч). По умолчанию timesheet (обратная совместимость).",
        )
        parser.add_argument(
            "--full",
            action="store_true",
            help="Полная сверка (scope=timesheet, без окна дат).",
        )

    def handle(self, *args, **options):
        days = options["days"]
        scope = options["scope"]
        run = run_scheduled_sync(days=days, scope=scope, full=options["full"])
        self.stdout.write(
            f"Scheduled sync done: scope={run.scope}, status={run.status}, "
            f"portals {run.portals_synced}/{run.portals_total}, "
            f"items={run.items_synced}, window={run.window_days}d."
        )
