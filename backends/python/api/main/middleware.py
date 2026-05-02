import logging
import time

from django.utils.deprecation import MiddlewareMixin

from .models import RequestLog


logger = logging.getLogger(__name__)


class RequestLoggingMiddleware(MiddlewareMixin):
    MAX_BODY_LENGTH = 2000
    SKIPPED_PATH_PREFIXES = (
        "/api/logs",
        "/api/health",
        "/healthz",
    )

    def process_request(self, request):
        request.start_time = time.time()

    def process_response(self, request, response):
        if not hasattr(request, "start_time"):
            return response

        duration = (time.time() - request.start_time) * 1000

        if self._should_skip_logging(request, response):
            return response

        try:
            req_body = request.body.decode("utf-8") if request.body else ""
        except Exception:
            req_body = "[Binary/Non-UTF8]"

        try:
            if hasattr(response, "content"):
                res_body = response.content.decode("utf-8")
            elif hasattr(response, "streaming_content"):
                res_body = "[Streaming Content]"
            else:
                res_body = ""
        except Exception:
            res_body = "[Binary/Non-UTF8]"

        try:
            RequestLog.objects.create(
                method=request.method,
                path=request.path,
                status_code=response.status_code,
                duration_ms=duration,
                request_body=self._truncate_body(req_body),
                response_body=self._truncate_body(res_body),
            )
        except Exception as e:
            logger.warning("Request logging failed: %s", e)

        return response

    def _should_skip_logging(self, request, response) -> bool:
        if any(request.path.startswith(prefix) for prefix in self.SKIPPED_PATH_PREFIXES):
            return True

        # High-volume successful reads overwhelm the DB and add low diagnostic value.
        if request.method in {"GET", "HEAD", "OPTIONS"} and response.status_code < 400:
            return True

        return False

    def _truncate_body(self, value: str) -> str:
        if len(value) <= self.MAX_BODY_LENGTH:
            return value
        return value[: self.MAX_BODY_LENGTH] + "... [Truncated]"


class ApiTrailingSlashNormalizeMiddleware(MiddlewareMixin):
    """
    Normalize trailing slash for API routes so `/api/.../` is resolved as `/api/...`.

    This prevents accidental fallback to SPA catch-all when proxy/client appends
    a trailing slash to API endpoints.
    """

    API_PREFIX = "/api"

    def process_request(self, request):
        path = request.path_info or ""
        if not path.startswith(self.API_PREFIX):
            return None

        if path in {"/api", "/api/"}:
            normalized = "/api"
        elif path.endswith("/"):
            normalized = path.rstrip("/")
        else:
            normalized = path

        if normalized != path:
            request.path_info = normalized
            request.META["PATH_INFO"] = normalized

        return None
