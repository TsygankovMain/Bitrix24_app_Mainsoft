import logging
import re
import time

from django.utils.deprecation import MiddlewareMixin

from .models import RequestLog


logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Secret redaction
# ---------------------------------------------------------------------------

# Keys whose values must be masked in any serialised body or header.
_SECRET_KEYS = (
    "AUTH_ID",
    "REFRESH_ID",
    "access_token",
    "refresh_token",
    "token",
    "Authorization",
)

# Regex explanation (groups):
#   1: optional opening quote before key name      ("  or empty)
#   2: the key name itself
#   3: optional closing quote after key name       ("  or empty)
#   4: separator — JSON colon (with optional surrounding space + opening quote)
#       or form equals sign (with optional surrounding space)
#   5: the secret value to replace
_keys_pattern = '|'.join(re.escape(k) for k in _SECRET_KEYS)
_JSON_OR_FORM_RE = re.compile(
    r'(?i)'
    r'("?)('  + _keys_pattern + r')("?)'   # groups 1-3: optional-quote KEY optional-quote
    r'(\s*:\s*"|\s*=\s*)'                   # group 4: separator (JSON colon or form equals)
    r'([^"\s&,}\]]+|"[^"]*")',              # group 5: value (unquoted or double-quoted)
    re.IGNORECASE,
)

_BEARER_RE = re.compile(r'(Bearer\s+)\S+', re.IGNORECASE)


def _redact_secrets(text: str) -> str:
    """Replace secret field values in *text* with '***'.

    Handles JSON (``"key": "value"``), form-encoded (``key=value``), and
    Authorization header (``Bearer <token>``) formats.  Key names are
    preserved; only the values are replaced.
    """
    if not text:
        return text

    # Redact Bearer tokens first (independent pattern).
    text = _BEARER_RE.sub(r'\1***', text)

    # Redact key/value pairs, preserving key name and separator structure.
    def _replace(m: re.Match) -> str:
        open_q, key, close_q, sep, _val = (
            m.group(1), m.group(2), m.group(3), m.group(4), m.group(5),
        )
        # If separator ends with a quote the value was JSON-quoted: close with quote too.
        if sep.rstrip().endswith('"'):
            return f'{open_q}{key}{close_q}{sep}***"'
        return f'{open_q}{key}{close_q}{sep}***'

    text = _JSON_OR_FORM_RE.sub(_replace, text)
    return text


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------


class RequestLoggingMiddleware(MiddlewareMixin):
    MAX_BODY_LENGTH = 2000
    SKIPPED_PATH_PREFIXES = (
        "/api/logs",
        "/api/health",
        "/healthz",
        "/api/getToken",
        "/api/install",
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
                request_body=self._truncate_body(_redact_secrets(req_body)),
                response_body=self._truncate_body(_redact_secrets(res_body)),
                bitrix24_account=getattr(request, "bitrix24_account", None),
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
