import ast
import json
from typing import Any, Iterable, List, Mapping


def normalize_employee_id(value: Any) -> str:
    if value in (None, "") or isinstance(value, bool):
        return ""

    if isinstance(value, (list, tuple)):
        for item in value:
            normalized = normalize_employee_id(item)
            if normalized:
                return normalized
        return ""

    if isinstance(value, int):
        return str(value)

    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else str(value).strip()

    value_str = str(value).strip()
    if not value_str:
        return ""

    if value_str.startswith("[") and value_str.endswith("]"):
        for parser in (json.loads, ast.literal_eval):
            try:
                parsed = parser(value_str)
            except (ValueError, SyntaxError, TypeError, json.JSONDecodeError):
                continue

            if isinstance(parsed, (list, tuple)):
                return normalize_employee_id(parsed)

    if value_str.endswith(".0") and value_str[:-2].isdigit():
        return value_str[:-2]

    return value_str


def extract_bitrix_user_id(value: Any) -> str:
    normalized = normalize_employee_id(value)
    return normalized if normalized.isdigit() else ""


def build_employee_id_aliases(values: Iterable[Any]) -> List[str]:
    aliases: List[str] = []
    seen = set()

    for value in values:
        raw = "" if value in (None, "") else str(value).strip()
        normalized = normalize_employee_id(value)
        candidates = [raw, normalized]
        if normalized:
            candidates.append(json.dumps([normalized], ensure_ascii=False))
            candidates.append(str([normalized]))
            if normalized.isdigit():
                candidates.append(f"[{normalized}]")

        for candidate in candidates:
            if candidate and candidate not in seen:
                seen.add(candidate)
                aliases.append(candidate)

    return aliases


def resolve_employee_name(
    user_map: Mapping[str, str],
    employee_id: Any,
    fallback_prefix: str = "Сотрудник",
    empty_name: str = "Без сотрудника",
) -> str:
    raw = "" if employee_id in (None, "") else str(employee_id).strip()
    normalized = normalize_employee_id(employee_id)

    for key in (normalized, raw):
        if key and user_map.get(key):
            return user_map[key]

    display_id = normalized or raw
    if display_id:
        return f"{fallback_prefix} {display_id}"
    return empty_name
