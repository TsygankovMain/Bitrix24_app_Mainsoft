import json
from functools import wraps


def collect_request_data(view_func):
    """
    Decorator that collects GET and POST parameters into request.data
    Supports both single values and lists for parameters
    """

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        try:
            params = json.loads(request.body.decode("utf-8"))
        except ValueError:
            params = {}

        # json.loads может успешно разобрать НЕ-объект (список/число/строку/
        # true). `params or {}` гасит только ЛОЖНЫЕ значения (None, [], 0, "",
        # False) — истинный не-словарь проходил насквозь как request.data, и
        # либо request.data[key] = ... ниже падало (list/str не поддерживают
        # присвоение по строковому ключу), либо потребитель (например,
        # auth_required.py: dict(request.data or {})) падал на конструкторе
        # словаря. Явная проверка типа вместо истинности значения.
        request.data = params if isinstance(params, dict) else {}

        # Process GET parameters
        for key in request.GET:
            values = request.GET.getlist(key)
            # If multiple values exist, store as list, else store single value
            request.data[key] = values if len(values) > 1 else values[0]

        # Process POST parameters
        for key in request.POST:
            values = request.POST.getlist(key)
            # POST parameters override GET parameters with same name
            # Store as list if multiple values, else single value
            request.data[key] = values if len(values) > 1 else values[0]

        return view_func(request, *args, **kwargs)

    return wrapper
