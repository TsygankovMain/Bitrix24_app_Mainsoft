import { test } from 'node:test'
import assert from 'node:assert/strict'
import { addOneYear, plannedAmount } from '../app/types/project-creation'

test('addOneYear: обычная дата', () => {
  assert.equal(addOneYear('2026-07-28'), '2027-07-28')
})

test('addOneYear: 29 февраля переносится на 28-е', () => {
  assert.equal(addOneYear('2028-02-29'), '2029-02-28')
})

test('addOneYear: пустая строка не ломается', () => {
  assert.equal(addOneYear(''), '')
})

test('plannedAmount: часы × ставка', () => {
  assert.equal(plannedAmount('10', '1500'), 15000)
})

test('plannedAmount: без часов — null, а не ноль', () => {
  assert.equal(plannedAmount('', '1500'), null)
})

test('plannedAmount: запятая как десятичный разделитель', () => {
  assert.equal(plannedAmount('1,5', '1000'), 1500)
})
