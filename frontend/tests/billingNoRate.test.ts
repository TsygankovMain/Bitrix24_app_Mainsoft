import test from 'node:test'
import assert from 'node:assert/strict'

import { noRateLineKeys, summarizeBillingNoRate } from '../app/utils/billingNoRate'
import { createBillingLineDrafts, toggleDraftExcluded } from '../app/utils/billingPreview'

function drafts() {
  return createBillingLineDrafts([
    { project_id: '1', title: 'Разработка', hours: 10, rate: 3000, amount: 30000 },
    { project_id: '2', title: 'Поддержка', hours: 8, rate: 0, amount: 0 },
    { project_id: '3', title: 'Внедрение', hours: 2, rate: 0, amount: 0 },
  ])
}

test('summarizeBillingNoRate: считает часы без цены и оценку потери по средней', () => {
  const summary = summarizeBillingNoRate(drafts(), { code: 'no_rate', count: 12 })

  assert.equal(summary.present, true)
  assert.equal(summary.entriesCount, 12)
  assert.equal(summary.lines.length, 2)
  assert.equal(summary.zeroHours, 10)
  assert.equal(summary.averageRate, 3000)
  assert.equal(summary.estimatedLoss, 30000)
  assert.deepEqual(summary.projectTitles, ['Поддержка', 'Внедрение'])
})

test('summarizeBillingNoRate: средняя считается по часам, а не по строкам', () => {
  const list = createBillingLineDrafts([
    { title: 'Дорогая', hours: 1, rate: 5000, amount: 5000 },
    { title: 'Дешёвая', hours: 9, rate: 1000, amount: 9000 },
    { title: 'Без цены', hours: 4, rate: 0, amount: 0 },
  ])
  const summary = summarizeBillingNoRate(list, { code: 'no_rate', count: 4 })

  // (5000 + 9000) / (1 + 9) = 1400 за час, а не среднее арифметическое 3000.
  assert.equal(summary.averageRate, 1400)
  assert.equal(summary.estimatedLoss, 5600)
})

test('summarizeBillingNoRate: исключённые строки в счёт не идут и в потерю тоже', () => {
  const list = drafts()
  list[1] = toggleDraftExcluded(list[1]!, true)

  const summary = summarizeBillingNoRate(list, { code: 'no_rate', count: 12 })

  assert.equal(summary.lines.length, 1)
  assert.equal(summary.zeroHours, 2)
  assert.equal(summary.estimatedLoss, 6000)
})

test('summarizeBillingNoRate: цены нет ни у одной строки — оценивать не по чему', () => {
  const list = createBillingLineDrafts([
    { title: 'Первая', hours: 5, rate: 0, amount: 0 },
    { title: 'Вторая', hours: 5, rate: 0, amount: 0 },
  ])
  const summary = summarizeBillingNoRate(list, { code: 'no_rate', count: 7 })

  assert.equal(summary.averageRate, 0)
  assert.equal(summary.estimatedLoss, 0)
  assert.equal(summary.zeroHours, 10)
})

test('summarizeBillingNoRate: предупреждения нет, но строку обнулили руками', () => {
  const list = createBillingLineDrafts([
    { title: 'Оплачиваемая', hours: 4, rate: 2000, amount: 8000 },
    { title: 'Обнулённая', hours: 4, rate: 0, amount: 0 },
  ])
  const summary = summarizeBillingNoRate(list, null)

  assert.equal(summary.present, true)
  assert.equal(summary.entriesCount, 0)
  assert.equal(summary.estimatedLoss, 8000)
})

test('summarizeBillingNoRate: всё со ставкой — плашки нет', () => {
  const list = createBillingLineDrafts([
    { title: 'Разработка', hours: 10, rate: 3000, amount: 30000 },
  ])
  const summary = summarizeBillingNoRate(list, null)

  assert.equal(summary.present, false)
  assert.deepEqual(summary.lines, [])
})

test('summarizeBillingNoRate: пустой вход не падает', () => {
  const summary = summarizeBillingNoRate(null, undefined)

  assert.equal(summary.present, false)
  assert.equal(summary.zeroHours, 0)
  assert.equal(summary.averageRate, 0)
})

test('noRateLineKeys: отдаёт ключи строк для исключения одним нажатием', () => {
  const summary = summarizeBillingNoRate(drafts(), { code: 'no_rate', count: 2 })

  assert.deepEqual(noRateLineKeys(summary), ['line-1', 'line-2'])
})
