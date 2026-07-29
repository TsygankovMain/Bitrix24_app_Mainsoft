"""Тесты чистой проверки ИНН (длина + контрольная сумма, без Django и без сети).

Валидные тестовые номера не взяты "по памяти" — сгенерированы и перепроверены
прогоном самой контрольной суммы перед написанием теста (см. inn-backend-report.md
и историю сессии): 7707083893 и 500100732259 дополнительно совпадают с
реальными широко публикуемыми примерами (Сбербанк / тестовый ИНН физлица).
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
        # str.isdigit() истинно для символов вроде "⁴" (верхний индекс) и
        # аравийско-индийских цифр, но int("⁴") бросает ValueError — наивная
        # проверка text.isdigit() пропустила бы такую строку дальше и
        # уронила бы контрольную сумму необработанным исключением (500
        # вместо "понятной ошибки", см. докстринг validate_inn). Проверяем
        # оба случая: превращается в понятный текст ошибки, не в exception.
        for inn in ("⁴707083893", "١٢٣٤٥٦٧٨٩٠"):
            with self.subTest(inn=inn):
                result = validate_inn(inn)  # не должно бросить исключение
                self.assertIsNotNone(result)

    def test_bad_checksum_10_digits_is_invalid(self):
        # Правильная длина, последняя (контрольная) цифра испорчена намеренно.
        self.assertIsNotNone(validate_inn("7707083894"))

    def test_bad_checksum_12_digits_is_invalid(self):
        self.assertIsNotNone(validate_inn("773605000381"))

    def test_blank_and_bad_checksum_produce_different_messages(self):
        # Не обязаны совпадать текстом — но обе ветки обязаны быть
        # различимы, иначе с фронта не понять, что именно поправить.
        blank_error = validate_inn("")
        checksum_error = validate_inn("7707083894")
        length_error = validate_inn("123")
        digits_error = validate_inn("770708389A")
        messages = {blank_error, checksum_error, length_error, digits_error}
        self.assertEqual(len(messages), 4, "ожидались четыре различных сообщения об ошибке")

    def test_does_not_raise_on_arbitrary_garbage(self):
        # Оборона по всему периметру: что угодно из JSON-тела не должно
        # ронять validate_inn необработанным исключением.
        for garbage in (None, "", [], {}, 123, True, "🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉"):
            with self.subTest(value=garbage):
                result = validate_inn(garbage)
                self.assertTrue(result is None or isinstance(result, str))
