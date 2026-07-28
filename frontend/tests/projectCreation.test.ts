import { test } from 'node:test'
import assert from 'node:assert/strict'
import { addOneYear, plannedAmount } from '../app/types/project-creation'
import { stepBadgeClass, stepLabel } from '../app/utils/projectCreationLabels'

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

test('stepLabel: каждый статус имеет человеческий текст', () => {
  const make = (status: string) => ({ status, id: null, name: '', candidates: [], error: null }) as never
  assert.equal(stepLabel(make('created')), '✓ создано')
  assert.equal(stepLabel(make('found')), '✓ найдено')
  assert.equal(stepLabel(make('skipped')), '— пропущено')
  assert.equal(stepLabel(make('ambiguous')), '⚠ уточните')
  assert.equal(stepLabel(make('error')), '✗ ошибка')
})

test('stepLabel: неизвестный статус не роняет интерфейс', () => {
  assert.equal(stepLabel({ status: 'xxx' } as never), '— пропущено')
})

// 'skipped' и 'ambiguous' обязаны отличаться цветом от 'error' так же, как
// текстом: иначе быстрый взгляд на бейдж читает "пропущено" или "уточните"
// как сбой (см. бриф задачи 8, раздел про семантику ответа).
test('stepBadgeClass: успех — зелёный, пропущено — нейтральный, уточните — жёлтый, ошибка — красный', () => {
  const make = (status: string) => ({ status, id: null, name: '', candidates: [], error: null }) as never
  assert.equal(stepBadgeClass(make('created')), 'bg-emerald-100 text-emerald-700')
  assert.equal(stepBadgeClass(make('found')), 'bg-emerald-100 text-emerald-700')
  assert.equal(stepBadgeClass(make('skipped')), 'bg-slate-100 text-slate-500')
  assert.equal(stepBadgeClass(make('ambiguous')), 'bg-amber-100 text-amber-700')
  assert.equal(stepBadgeClass(make('error')), 'bg-rose-100 text-rose-700')
  assert.notEqual(stepBadgeClass(make('skipped')), stepBadgeClass(make('error')))
  assert.notEqual(stepBadgeClass(make('ambiguous')), stepBadgeClass(make('error')))
})

test('stepBadgeClass: неизвестный статус не роняет интерфейс', () => {
  assert.equal(stepBadgeClass({ status: 'xxx' } as never), 'bg-slate-100 text-slate-500')
})
