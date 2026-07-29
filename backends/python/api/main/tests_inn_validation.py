"""Тесты чистой проверки ИНН (длина + состав символов, без Django и без сети).

Контрольная сумма сознательно не проверяется (см. докстринг inn_validation.py)
— поэтому "валидные" номера ниже валидны просто по форме (длина + ASCII-цифры),
проверка их реальной контрольной суммы не требуется. Тем не менее большинство
взято не "по памяти", а из реальных широко публикуемых примеров (7707083893 —
Сбербанк, 500100732259 — тестовый ИНН физлица), чтобы не гадать на глаз.
"""
from django.test import SimpleTestCase

from .inn_validation import INN_LENGTHS, is_valid_inn, normalize_inn, validate_inn


class NormalizeInnTest(SimpleTestCase):
    def test_strips_surrounding_whitespace(self):
        self.assertEqual(normalize_inn("  7707083893  "), "7707083893")

    def test_none_becomes_empty_string(self):
        self.assertEqual(normalize_inn(None), "")

    def test_coerces_non_string_input(self):
        # form.get("inn") идёт из JSON-тела запроса — теоретически может
        # прийти числом, если фронт (или сторонний клиент API) сериализует
        # поле как число, а не строку.
        self.assertEqual(normalize_inn(7707083893), "7707083893")

    def test_internal_whitespace_is_not_stripped(self):
        # strip() чистит только края — пробел ВНУТРИ номера обязан остаться
        # и провалить проверку "только цифры" в validate_inn, а не быть
        # молча склеенным.
        self.assertEqual(normalize_inn(" 7707 083893 "), "7707 083893")


class ValidateInnValidNumbersTest(SimpleTestCase):
    def test_valid_legal_entity_inn_10_digits(self):
        for inn in ("7707083893", "7736050003", "7707049388", "7710140679", "5001007329"):
            with self.subTest(inn=inn):
                self.assertIsNone(validate_inn(inn))
                self.assertTrue(is_valid_inn(inn))

    def test_valid_individual_inn_12_digits(self):
        for inn in ("500100732259", "773605000380"):
            with self.subTest(inn=inn):
                self.assertIsNone(validate_inn(inn))
                self.assertTrue(is_valid_inn(inn))

    def test_surrounding_whitespace_is_tolerated(self):
        self.assertIsNone(validate_inn("  7707083893  "))

    def test_inn_lengths_constant_matches_validated_lengths(self):
        self.assertEqual(set(INN_LENGTHS), {10, 12})


class ValidateInnInvalidNumbersTest(SimpleTestCase):
    def test_blank_is_invalid(self):
        for blank in ("", None, "   "):
            with self.subTest(value=blank):
                self.assertIsNotNone(validate_inn(blank))
                self.assertFalse(is_valid_inn(blank))

    def test_wrong_length_is_invalid(self):
        for inn in ("770708389", "77070838931", "1", "123456789012345"):
            with self.subTest(inn=inn):
                self.assertIsNotNone(validate_inn(inn))

    def test_non_digit_characters_are_invalid(self):
        for inn in ("770708389A", "77-07083893", "7707 083893", "ИНН7707083893", "77.07083893"):
            with self.subTest(inn=inn):
                self.assertIsNotNone(validate_inn(inn))

    def test_unicode_digit_lookalikes_are_rejected_not_crash(self):
        # str.isdigit() истинно и для "⁴" (верхний индекс), и для
        # аравийско-индийских/тайских/деванагари цифр — но ветвятся они
        # по-разному ниже по стеку: int("⁴") бросает ValueError, а
        # int(<тайская/деванагари запись>) молча возвращает обычное число
        # (см. докстринг модуля — три последних значения ниже все дают
        # int(...) == 7707083893, тот же валидный номер, что и первым в
        # test_valid_legal_entity_inn_10_digits выше и в VALID_INN других
        # тестовых файлов). Наивная проверка text.isdigit() пропустила бы
        # ЛЮБУЮ из этих строк дальше как "цифры" — а дальше либо
        # необработанный ValueError (500 вместо понятной ошибки), либо, что
        # опаснее, тихая запись в CRM клиента ИНН из юникод-цифр, который
        # выглядит числом, но не находится обычным поиском (см. докстринг
        # _is_ascii_digits). Проверяем, что все случаи превращаются в понятный
        # текст ошибки, а не в exception и не в "валиден".
        for inn in (
            "⁴707083893",  # верхний индекс — int() бросает ValueError
            "١٢٣٤٥٦٧٨٩٠",  # аравийско-индийские цифры — int() не бросает
            "٧٧٠٧٠٨٣٨٩٣",  # аравийско-индийские цифры того же числа, что VALID_INN
            "๗๗๐๗๐๘๓๘๙๓",  # тайские цифры того же числа — int() не бросает
            "७७०७०८३८९३",  # деванагари того же числа — int() не бросает
        ):
            with self.subTest(inn=inn):
                result = validate_inn(inn)  # не должно бросить исключение
                self.assertIsNotNone(result)

    def test_each_invalid_reason_produces_a_different_message(self):
        # Три оставшихся ветки (пусто / не-ASCII-цифры / неверная длина) не
        # обязаны совпадать текстом — но обязаны быть различимы, иначе с
        # фронта не понять, что именно поправить.
        blank_error = validate_inn("")
        digits_error = validate_inn("770708389A")
        length_error = validate_inn("123")
        messages = {blank_error, digits_error, length_error}
        self.assertEqual(len(messages), 3, "ожидались три различных сообщения об ошибке")

    def test_does_not_raise_on_arbitrary_garbage(self):
        # Оборона по всему периметру: что угодно из JSON-тела не должно
        # ронять validate_inn необработанным исключением.
        for garbage in (None, "", [], {}, 123, True, "🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉"):
            with self.subTest(value=garbage):
                result = validate_inn(garbage)
                self.assertTrue(result is None or isinstance(result, str))
