import test from 'node:test'
import assert from 'node:assert/strict'

import {
  draftFromItem,
  makeTaskEntryDraft,
  normalizeDraftDate,
  quickDateOptions,
  toDateInputValue,
  validateEntryDraft,
  validateSplit
} from '../app/utils/taskTabEntry'

test('makeTaskEntryDraft: новая запись — час, учитываем, сегодняшняя дата', () => {
  const draft = makeTaskEntryDraft({ taskId: '300', employeeId: '10', today: new Date(2026, 7, 9, 15, 0) })

  assert.equal(draft.id, null)
  assert.equal(draft.taskId, '300')
  assert.equal(draft.employeeId, '10')
  assert.equal(draft.hours, 1)
  assert.equal(draft.isConsidered, true)
  assert.equal(draft.splitInvert, false)
  assert.equal(draft.date, '2026-08-09')
})

test('makeTaskEntryDraft: поздний вечер не превращается в завтра', () => {
  const draft = makeTaskEntryDraft({ taskId: '300', today: new Date(2026, 7, 9, 23, 30) })

  assert.equal(draft.date, '2026-08-09')
})

test('draftFromItem: запись дерева превращается в черновик правки', () => {
  const draft = draftFromItem({
    id: '42',
    hours: 2.5,
    isConsidered: true,
    description: 'Разбор',
    employeeId: '7',
    employeeName: 'Иванов',
    date: '2026-04-05T00:00:00+03:00'
  }, '300')

  assert.equal(draft.id, '42')
  assert.equal(draft.taskId, '300')
  assert.equal(draft.hours, 2.5)
  assert.equal(draft.date, '2026-04-05')
  assert.equal(draft.splitHours, 0)
})

test('draftFromItem: часы строкой приводятся к числу', () => {
  const draft = draftFromItem({
    id: '42',
    hours: '2' as unknown as number,
    isConsidered: false,
    description: '',
    employeeId: '7',
    employeeName: 'Иванов'
  }, '300')

  assert.equal(draft.hours, 2)
  assert.equal(typeof draft.hours, 'number')
})

test('normalizeDraftDate: отрезает время и зону', () => {
  assert.equal(normalizeDraftDate('2026-04-05T10:00:00+03:00'), '2026-04-05')
  assert.equal(normalizeDraftDate('2026-04-05'), '2026-04-05')
  assert.equal(normalizeDraftDate(''), '')
  assert.equal(normalizeDraftDate('не дата'), '')
})

test('validateEntryDraft: ноль часов сохранять нельзя', () => {
  assert.equal(
    validateEntryDraft({ hours: 0, employeeId: '7', date: '2026-04-05' }),
    'Укажите часы больше нуля.'
  )
  assert.equal(
    validateEntryDraft({ hours: -1, employeeId: '7', date: '2026-04-05' }),
    'Укажите часы больше нуля.'
  )
})

test('validateEntryDraft: больше суток за день — опечатка, а не трудовой подвиг', () => {
  assert.ok(validateEntryDraft({ hours: 25, employeeId: '7', date: '2026-04-05' }))
  assert.equal(validateEntryDraft({ hours: 24, employeeId: '7', date: '2026-04-05' }), null)
})

test('validateEntryDraft: сотрудник и дата обязательны', () => {
  assert.equal(validateEntryDraft({ hours: 1, employeeId: '', date: '2026-04-05' }), 'Выберите сотрудника.')
  assert.equal(validateEntryDraft({ hours: 1, employeeId: '7', date: '' }), 'Укажите дату списания.')
})

test('validateEntryDraft: заполненный черновик проходит', () => {
  assert.equal(validateEntryDraft({ hours: 1.25, employeeId: 7, date: '2026-04-05' }), null)
})

test('validateSplit: несохранённую запись делить нечего', () => {
  assert.equal(
    validateSplit({ id: null, hours: 2, splitHours: 1 }),
    'Разделить можно только сохранённую запись.'
  )
})

test('validateSplit: ноль и вся запись целиком не проходят', () => {
  assert.ok(validateSplit({ id: '1', hours: 2, splitHours: 0 }))
  assert.ok(validateSplit({ id: '1', hours: 2, splitHours: 2 }))
  assert.ok(validateSplit({ id: '1', hours: 2, splitHours: 3 }))
})

test('validateSplit: часть записи отделить можно', () => {
  assert.equal(validateSplit({ id: '1', hours: 2, splitHours: 0.5 }), null)
})

test('toDateInputValue: локальный календарь, а не UTC', () => {
  assert.equal(toDateInputValue(new Date(2026, 0, 1, 0, 30)), '2026-01-01')
  assert.equal(toDateInputValue(new Date(2026, 11, 31, 23, 59)), '2026-12-31')
})

test('quickDateOptions: сегодня и вчера', () => {
  const options = quickDateOptions(new Date(2026, 2, 1, 12, 0))

  assert.deepEqual(options, [
    { label: 'Сегодня', value: '2026-03-01' },
    { label: 'Вчера', value: '2026-02-28' }
  ])
})
