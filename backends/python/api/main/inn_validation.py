"""ИНН — чистая проверка формата и контрольных сумм по стандартной схеме ФНС.

Без Django и без сети — как project_creation_defaults.py по соседству (см.
докстринг того модуля про то же требование): та же арифметика дублируется
на фронте (frontend/app/utils/, задача идёт отдельно после этой), и обе
стороны обязаны проверяться одинаково, без моков сети или Django. Бэкендная
копия обязательна НЕЗАВИСИМО от фронтовой — фронт можно обойти прямым POST
на create_project_board (см. докстринг ensure_company в
project_creation_service.py).

Правила: 10 цифр — юридическое лицо, одна контрольная цифра (вес-11 по
первым 9 цифрам). 12 цифр — ИП/физлицо, две контрольные цифры (вес-10 по
первым 10, вес-11 по первым 11). Тестовые номера в tests_inn_validation.py
не взяты "на глаз" — сгенерированы и перепроверены прогоном этой же
арифметики перед тем, как стать тестом (см. inn-backend-report.md).
"""
from typing import Any, Optional, Tuple

# Тот же набор длин, что и INN_LENGTHS в company_search_service.py — не
# импортируется оттуда намеренно: тот модуль тянет Django (cache.cache), а
# этот обязан остаться проверяемым без Django (см. докстринг выше). Две
# копии одной константы — сознательный выбор в пользу независимости модулей,
# а не забытый дубль: значение (10, 12) — стандарт ФНС, меняться не должно.
INN_LENGTHS: Tuple[int, int] = (10, 12)

_ASCII_DIGITS = frozenset("0123456789")

_WEIGHTS_10 = (2, 4, 10, 3, 5, 9, 4, 6, 8)
_WEIGHTS_11 = (7, 2, 4, 10, 3, 5, 9, 4, 6, 8)
_WEIGHTS_12 = (3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8)

ERROR_BLANK = "ИНН не указан."
ERROR_NOT_DIGITS = "ИНН должен состоять только из цифр."
ERROR_LENGTH = "ИНН должен содержать 10 цифр (юридическое лицо) или 12 цифр (ИП/физлицо)."
ERROR_CHECKSUM = "Некорректная контрольная сумма ИНН — проверьте номер."


def normalize_inn(value: Any) -> str:
    """Строка без пробелов по краям. `None` -> "". Состав символов не проверяет —
    для этого validate_inn ниже."""
    if value is None:
        return ""
    return str(value).strip()


def _is_ascii_digits(text: str) -> bool:
    """`text.isdigit()` — ловушка: True для символов вида "⁴" (верхний индекс)
    и аравийско-индийских цифр, а `int("⁴")` бросает ValueError. Наивная
    проверка пропустила бы такую строку в контрольную сумму и уронила бы её
    необработанным исключением — 500 вместо понятной ошибки (см. докстринг
    validate_inn и tests_inn_validation.test_unicode_digit_lookalikes_are_
    rejected_not_crash, где это воспроизведено). Явный набор ASCII-цифр —
    единственная проверка здесь, которой можно доверять."""
    return bool(text) and all(ch in _ASCII_DIGITS for ch in text)


def _control_digit(digits: str, weights: Tuple[int, ...]) -> int:
    total = sum(int(d) * w for d, w in zip(digits, weights))
    return (total % 11) % 10


def _checksum_ok(digits: str) -> bool:
    """Вызывается только когда len(digits) уже проверена как 10 или 12
    (см. validate_inn) — здесь это предположение, а не повторная проверка."""
    if len(digits) == 10:
        return _control_digit(digits[:9], _WEIGHTS_10) == int(digits[9])
    n11 = _control_digit(digits[:10], _WEIGHTS_11)
    n12 = _control_digit(digits[:11], _WEIGHTS_12)
    return n11 == int(digits[10]) and n12 == int(digits[11])


def validate_inn(value: Any) -> Optional[str]:
    """`None`, если ИНН валиден; иначе — текст причины на русском (готов для
    прямого показа сотруднику).

    Порядок проверок осознанный: сперва форма (пусто -> только цифры ->
    длина), и только для полностью правдоподобной по форме строки —
    контрольная сумма. Так сообщение указывает на первую реальную проблему
    ввода, а не тонет в "неверная контрольная сумма" там, где просто не
    хватает цифры или закралась буква.

    Никогда не бросает исключение — на любом мусоре из JSON-тела запроса
    (число, список, словарь, юникод-цифры) возвращает текст ошибки, а не
    падает (см. test_does_not_raise_on_arbitrary_garbage).
    """
    text = normalize_inn(value)
    if not text:
        return ERROR_BLANK
    if not _is_ascii_digits(text):
        return ERROR_NOT_DIGITS
    if len(text) not in INN_LENGTHS:
        return ERROR_LENGTH
    if not _checksum_ok(text):
        return ERROR_CHECKSUM
    return None


def is_valid_inn(value: Any) -> bool:
    return validate_inn(value) is None
