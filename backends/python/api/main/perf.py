"""Lightweight performance profiler for report endpoints.

Usage:

    from .perf import ReportProfiler

    profiler = ReportProfiler("report_employee_project")
    with profiler.stage("queryset"):
        queryset = _get_filtered_timesheet_queryset(request)
    with profiler.stage("materialize"):
        rows = materialize_rows(queryset, TREE_REPORT_FIELDS)
    profiler.set_metric("rows", len(rows))
    response = JsonResponse(...)
    profiler.attach_to_response(response)
    profiler.log()
    return response

The profiler logs a single INFO line tagged ``[REPORT_PERF]`` and, in DEBUG
mode, attaches an ``X-Report-Timings`` header so the frontend can read it
from the network panel without reading server logs.

No external dependencies — uses ``time.perf_counter`` and standard logging.
"""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from typing import Any, Dict, Iterator, Optional

from django.conf import settings


logger = logging.getLogger(__name__)


class ReportProfiler:
    """Collects per-stage timings for a single report request."""

    def __init__(self, report_name: str, account_id: Optional[Any] = None):
        self.report_name = report_name
        self.account_id = account_id
        self._timings_ms: Dict[str, float] = {}
        self._metrics: Dict[str, Any] = {}
        self._started_at = time.perf_counter()

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        """Context manager that records the wall-clock duration of a block."""
        start = time.perf_counter()
        try:
            yield
        finally:
            duration_ms = (time.perf_counter() - start) * 1000.0
            # If the same stage is entered twice, accumulate.
            self._timings_ms[name] = self._timings_ms.get(name, 0.0) + duration_ms

    def set_metric(self, name: str, value: Any) -> None:
        """Attach an arbitrary metric (e.g. row count, user count) to the log line."""
        self._metrics[name] = value

    @property
    def total_ms(self) -> float:
        return (time.perf_counter() - self._started_at) * 1000.0

    def _format_timings(self) -> str:
        parts = [f"{name}={ms:.0f}ms" for name, ms in self._timings_ms.items()]
        parts.append(f"total={self.total_ms:.0f}ms")
        return ",".join(parts)

    def _format_metrics(self) -> str:
        if not self._metrics:
            return ""
        return " " + " ".join(f"{k}={v}" for k, v in self._metrics.items())

    def log(self) -> None:
        """Emit a single structured INFO line."""
        account_part = f" account={self.account_id}" if self.account_id is not None else ""
        logger.info(
            "[REPORT_PERF] %s%s%s timings=%s",
            self.report_name,
            account_part,
            self._format_metrics(),
            self._format_timings(),
        )

    def attach_to_response(self, response) -> None:
        """In DEBUG mode, expose timings as an HTTP header for DevTools.

        The header is intentionally short and human-readable.
        """
        if not getattr(settings, "DEBUG", False):
            return
        try:
            response["X-Report-Timings"] = self._format_timings()
            if self._metrics:
                response["X-Report-Metrics"] = " ".join(f"{k}={v}" for k, v in self._metrics.items())
        except Exception:  # response may not support setitem in some test stubs
            pass
