import logging
import traceback
from functools import wraps
from http import HTTPStatus

from django.http import JsonResponse
from main.models import SystemLog


def log_errors(message: str):
    def inner(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                response = func(*args, **kwargs)
            except Exception as exc:
                tb = traceback.format_exc()
                logging.error(message + f", args={args}, kwargs={kwargs}" + ": " + str(exc))
                
                # Save to SystemLog
                try:
                    SystemLog.objects.create(
                        level="ERROR",
                        module=message,
                        message=str(exc),
                        traceback=tb
                    )
                except Exception:
                    pass

                return JsonResponse({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
            else:
                return response
        return wrapper
    return inner
