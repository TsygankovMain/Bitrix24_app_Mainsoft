"""Management command: purge_request_logs

Deletes RequestLog and SystemLog entries older than N days (default 30).
Accumulated bodies may contain plaintext tokens, so full purge of aged
entries is intentional.

Usage:
    python manage.py purge_request_logs
    python manage.py purge_request_logs --days 7
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta

from main.models import RequestLog, SystemLog


class Command(BaseCommand):
    help = "Delete RequestLog and SystemLog entries older than --days days (default 30)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=30,
            help="Delete records older than this many days (default: 30).",
        )

    def handle(self, *args, **options):
        days = options["days"]
        cutoff = timezone.now() - timedelta(days=days)

        req_deleted, _ = RequestLog.objects.filter(timestamp__lt=cutoff).delete()
        sys_deleted, _ = SystemLog.objects.filter(timestamp__lt=cutoff).delete()

        self.stdout.write(
            f"Purged {req_deleted} RequestLog and {sys_deleted} SystemLog "
            f"entries older than {days} days (cutoff: {cutoff.isoformat()})."
        )
