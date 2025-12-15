import time
import json
from django.utils.deprecation import MiddlewareMixin
from .models import RequestLog

class RequestLoggingMiddleware(MiddlewareMixin):
    def process_request(self, request):
        request.start_time = time.time()
        
    def process_response(self, request, response):
        if not hasattr(request, 'start_time'):
            return response
            
        duration = (time.time() - request.start_time) * 1000
        
        # Skip logging for the log endpoints themselves to avoid clutter loops
        if request.path.startswith('/api/logs'):
            return response
            
        # Also maybe skip health check
        if request.path == '/api/health':
            return response

        try:
            req_body = request.body.decode('utf-8') if request.body else ""
        except:
            req_body = "[Binary/Non-UTF8]"
            
        try:
            if hasattr(response, 'content'):
                res_body = response.content.decode('utf-8')
                if len(res_body) > 5000:
                    res_body = res_body[:5000] + "... [Truncated]"
            elif hasattr(response, 'streaming_content'):
                 res_body = "[Streaming Content]"
            else:
                res_body = ""
        except:
            res_body = "[Binary/Non-UTF8]"

        try:
            RequestLog.objects.create(
                method=request.method,
                path=request.path,
                status_code=response.status_code,
                duration_ms=duration,
                request_body=req_body,
                response_body=res_body
            )
        except Exception as e:
            # Fail silently to not impact request
            print(f"Logging failed: {e}")
            pass
            
        return response
