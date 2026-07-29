import test from 'node:test'
import assert from 'node:assert/strict'

import {
  ERROR_BLANK,
  ERROR_LENGTH,
  ERROR_NOT_DIGITS,
  isValidInn,
  normalizeInn,
  validateInn,
} from '../app/utils/innValidation'

// Зеркалит backends/python/api/main/inn_validation.py — те же правила, тот
// же порядок проверок (пусто -> только ASCII-цифры -> длина), НЕ строже.
// Контрольную сумму сознательно не проверяем (решение заказчика, см.
// .superpowers/sdd/2026-07-28-create-project-button/inn-trim-report.md) —
// сам Битрикс её в интерфейсе создания реквизита не проверяет.

// --- normalizeInn ---

test('normalizeInn: обрезает пробелы по краям', () => {
  assert.equal(normalizeInn('  7707083893  '), '7707083893')
})

test('normalizeInn: null/undefined -> пустая строка, не бросает исключение', () => {
  assert.equal(normalizeInn(null), '')
  assert.equal(normalizeInn(undefined), '')
})

// --- validateInn: валидные номера (те же тестовые номера, что и в бэкендных тестах) ---

test('validateInn: 10 цифр (юрлицо) — валиден. 7707083893 — реальный ИНН Сбербанка, используется и в бэкендных тестах', () => {
  assert.equal(validateInn('7707083893'), null)
})

test('validateInn: 12 цифр (ИП/физлицо) — валиден. 500100732259 — широко публикуемый тестовый ИНН физлица, тот же пример, что и на бэкенде', () => {
  assert.equal(validateInn('500100732259'), null)
})

test('validateInn: пробелы по краям не мешают валидному номеру', () => {
  assert.equal(validateInn('  7707083893  '), null)
})

// --- validateInn: пусто ---

test('validateInn: пустая строка -> ERROR_BLANK', () => {
  assert.equal(validateInn(''), ERROR_BLANK)
})

test('validateInn: только пробелы -> ERROR_BLANK', () => {
  assert.equal(validateInn('   '), ERROR_BLANK)
})

test('validateInn: null/undefined -> ERROR_BLANK, не бросает исключение', () => {
  assert.equal(validateInn(null), ERROR_BLANK)
  assert.equal(validateInn(undefined), ERROR_BLANK)
})

// --- validateInn: не цифры ---

test('validateInn: буквы -> ERROR_NOT_DIGITS', () => {
  assert.equal(validateInn('770708389A'), ERROR_NOT_DIGITS)
})

test('validateInn: цифры с пробелом внутри -> ERROR_NOT_DIGITS (внутренние пробелы не схлопываются)', () => {
  assert.equal(validateInn('7707 083893'), ERROR_NOT_DIGITS)
})

// --- validateInn: длина ---

test('validateInn: 9 цифр — слишком коротко -> ERROR_LENGTH', () => {
  assert.equal(validateInn('770708389'), ERROR_LENGTH)
})

test('validateInn: 11 цифр — не 10 и не 12 -> ERROR_LENGTH', () => {
  assert.equal(validateInn('77070838931'), ERROR_LENGTH)
})

test('validateInn: 13 цифр — слишком длинно -> ERROR_LENGTH', () => {
  assert.equal(validateInn('5001007322599'), ERROR_LENGTH)
})

// --- validateInn: контрольная сумма сознательно НЕ проверяется ---

test('validateInn: 10 цифр с заведомо неверной контрольной суммой — валиден (контрольную сумму не проверяем)', () => {
  // Тот же пример, что и в inn-trim-report.md: 7707083894 отличается от
  // настоящего ИНН Сбербанка (7707083893) последней цифрой — контрольная
  // сумма не сходится, но состав символов и длина в порядке.
  assert.equal(validateInn('7707083894'), null)
})

test('validateInn: 12 цифр с заведомо неверной контрольной суммой — валиден (контрольную сумму не проверяем)', () => {
  assert.equal(validateInn('773605000381'), null)
})

// --- validateInn: юникод-цифры, похожие на настоящие, но не ASCII ---
// Главная ценность модуля (см. докстринг backends/python/api/main/inn_validation.py):
// у арабских/тайских/деванагари цифр str.isdigit() истинно и в отрыве от
// строгой ASCII-проверки такая строка выглядела бы валидным ИНН, хотя
// обычный поиск по ИНН (RQ_INN=<ascii-строка>) её не находит — символы
// другие при том же числовом значении.

test('validateInn: аравийско-индийские цифры (запись того же числа 7707083893) — отклонены, не приняты как валидные', () => {
  assert.equal(validateInn('٧٧٠٧٠٨٣٨٩٣'), ERROR_NOT_DIGITS)
})

test('validateInn: тайские цифры (запись того же числа 7707083893) — отклонены', () => {
  assert.equal(validateInn('๗๗๐๗๐๘๓๘๙๓'), ERROR_NOT_DIGITS)
})

test('validateInn: деванагари цифры (запись того же числа 7707083893) — отклонены', () => {
  assert.equal(validateInn('७७०७०८३८९३'), ERROR_NOT_DIGITS)
})

test('validateInn: верхний индекс ("⁴" и т.п.) — не ASCII-цифра, отклонена, не роняет функцию', () => {
  assert.equal(validateInn('⁴⁴⁴⁴⁴⁴⁴⁴⁴⁴'), ERROR_NOT_DIGITS)
})

// --- validateInn: произвольный мусор не бросает исключение ---

test('validateInn: число вместо строки — не бросает исключение', () => {
  assert.doesNotThrow(() => validateInn(7707083893))
})

test('validateInn: массив/объект — не бросает исключение, отклонены', () => {
  assert.doesNotThrow(() => validateInn(['7707083893']))
  assert.doesNotThrow(() => validateInn({ inn: '7707083893' }))
})

// --- isValidInn ---

test('isValidInn: true для валидного ИНН', () => {
  assert.equal(isValidInn('7707083893'), true)
})

test('isValidInn: false для невалидного ИНН', () => {
  assert.equal(isValidInn(''), false)
  assert.equal(isValidInn('123'), false)
  assert.equal(isValidInn('७७०७०८३८९३'), false)
})
