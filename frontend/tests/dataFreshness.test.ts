import test from 'node:test'
import assert from 'node:assert/strict'

import { formatDataFreshness, NEVER_SYNCED_TEXT } from '../app/utils/dataFreshness'

// Даты собираются локальными конструкторами, а строки — в форме без смещения
// (`2026-07-31T14:05:00`), которую спека ECMAScript трактует как локальное время.
// Поэтому тест не зависит от таймзоны машины.

test('formatDataFreshness: маркера нет — сообщаем, что данные не синхронизировались', () => {
  const now = new Date(2026, 6, 31, 18, 0)

  assert.equal(formatDataFreshness(null, now), NEVER_SYNCED_TEXT)
  assert.equal(formatDataFreshness(undefined, now), NEVER_SYNCED_TEXT)
  assert.match(formatDataFreshness(null, now), /не синхронизировались/)
})

test('formatDataFreshness: пустая и нечитаемая строка приравниваются к отсутствию маркера', () => {
  const now = new Date(2026, 6, 31, 18, 0)

  assert.equal(formatDataFreshness('', now), NEVER_SYNCED_TEXT)
  assert.equal(formatDataFreshness('   ', now), NEVER_SYNCED_TEXT)
  assert.equal(formatDataFreshness('не-дата', now), NEVER_SYNCED_TEXT)
})

test('formatDataFreshness: синк был сегодня — только время «данные на ЧЧ:ММ»', () => {
  const now = new Date(2026, 6, 31, 18, 0)

  assert.equal(formatDataFreshness('2026-07-31T14:05:00', now), 'данные на 14:05')
  // Ранний час не должен терять ведущий ноль
  assert.equal(formatDataFreshness('2026-07-31T09:07:00', now), 'данные на 09:07')
  // Полночь того же дня — всё ещё «сегодня»
  assert.equal(formatDataFreshness('2026-07-31T00:00:00', now), 'данные на 00:00')
})

test('formatDataFreshness: синк был раньше — в тексте появляется дата', () => {
  const now = new Date(2026, 6, 31, 18, 0)

  assert.equal(formatDataFreshness('2026-07-29T09:07:00', now), 'данные на 29.07.2026 09:07')
  // Вчерашние 23:59 — уже другой календарный день, дата обязана быть в тексте
  assert.equal(formatDataFreshness('2026-07-30T23:59:00', now), 'данные на 30.07.2026 23:59')
  // Тот же день и месяц, но другой год — не «сегодня»
  assert.equal(formatDataFreshness('2025-07-31T14:05:00', now), 'данные на 31.07.2025 14:05')
})
