import test from 'node:test'
import assert from 'node:assert/strict'

import {
  applyDraftRate,
  applyDraftTitle,
  buildBillingLinesPayload,
  createBillingLineDrafts,
  describeZeroAmountBlock,
  hasDraftEdits,
  recalcBillingTotals,
  round2,
  toggleDraftExcluded,
} from '../app/utils/billingPreview'

const PREVIEW_LINES = [
  { project_id: '10', title: 'Доработка CRM', hours: 12.5, rate: 3000, amount: 37500 },
  { project_id: '11', title: 'Поддержка', hours: 8, rate: 2500, amount: 20000 },
  { project_id: '12', title: 'Консультации', hours: 2, rate: 4000, amount: 8000 },
]

test('round2: копейки округляются один раз и без «плавающего» хвоста', () => {
  assert.equal(round2(0.1 + 0.2), 0.3)
  assert.equal(round2(1.005), 1.01)
  assert.equal(round2(Number.NaN), 0)
})

test('createBillingLineDrafts: строки приходят включёнными и без правок', () => {
  const drafts = createBillingLineDrafts(PREVIEW_LINES)

  assert.equal(drafts.length, 3)
  assert.equal(drafts[0].title, 'Доработка CRM')
  assert.equal(drafts[0].amount, 37500)
  assert.equal(drafts[0].excluded, false)
  assert.equal(drafts[0].titleEdited, false)
  assert.equal(drafts[0].rateEdited, false)
})

test('createBillingLineDrafts: сумму берём от сервера, а не пересчитываем', () => {
  const drafts = createBillingLineDrafts([
    { project_id: '1', title: 'НДС уже внутри', hours: 10, rate: 1000, amount: 9800 },
  ])

  assert.equal(drafts[0].amount, 9800)
})

test('createBillingLineDrafts: суммы нет — считаем сами, названия нет — подставляем', () => {
  const drafts = createBillingLineDrafts([{ project_id: '1', hours: 3, rate: 1500 }])

  assert.equal(drafts[0].amount, 4500)
  assert.equal(drafts[0].title, 'Работы по проекту')
})

test('createBillingLineDrafts: строки и запятые в числах не ломают расчёт', () => {
  const drafts = createBillingLineDrafts([
    { project_id: '1', title: 'Строкой', hours: '7,5', rate: '2 000', amount: null },
  ])

  assert.equal(drafts[0].hours, 7.5)
  assert.equal(drafts[0].rate, 2000)
  assert.equal(drafts[0].amount, 15000)
})

test('createBillingLineDrafts: не массив — пустой список, а не падение', () => {
  assert.deepEqual(createBillingLineDrafts(null), [])
  assert.deepEqual(createBillingLineDrafts(undefined), [])
})

test('applyDraftTitle: правка отмечается, пустой текст возвращает исходный', () => {
  const [draft] = createBillingLineDrafts(PREVIEW_LINES)

  const edited = applyDraftTitle(draft, 'Работы по договору 12/2026')
  assert.equal(edited.title, 'Работы по договору 12/2026')
  assert.equal(edited.titleEdited, true)

  const cleared = applyDraftTitle(edited, '   ')
  assert.equal(cleared.title, 'Доработка CRM')
  assert.equal(cleared.titleEdited, false)
})

test('applyDraftRate: сумма пересчитывается сразу, минус не принимается', () => {
  const [draft] = createBillingLineDrafts(PREVIEW_LINES)

  const cheaper = applyDraftRate(draft, 2000)
  assert.equal(cheaper.rate, 2000)
  assert.equal(cheaper.amount, 25000)
  assert.equal(cheaper.rateEdited, true)

  const negative = applyDraftRate(draft, -100)
  assert.equal(negative.rate, 0)
  assert.equal(negative.amount, 0)
})

test('applyDraftRate: возврат к исходной цене снимает пометку «изменено»', () => {
  const [draft] = createBillingLineDrafts(PREVIEW_LINES)
  const back = applyDraftRate(applyDraftRate(draft, 2000), 3000)

  assert.equal(back.rateEdited, false)
  assert.equal(back.amount, 37500)
})

test('recalcBillingTotals: итог по всем строкам', () => {
  const totals = recalcBillingTotals(createBillingLineDrafts(PREVIEW_LINES))

  assert.equal(totals.linesCount, 3)
  assert.equal(totals.excludedCount, 0)
  assert.equal(totals.totalHours, 22.5)
  assert.equal(totals.totalAmount, 65500)
  assert.equal(totals.issuable, true)
})

test('recalcBillingTotals: исключённая строка уходит и из часов, и из суммы', () => {
  const drafts = createBillingLineDrafts(PREVIEW_LINES)
  drafts[1] = toggleDraftExcluded(drafts[1])

  const totals = recalcBillingTotals(drafts)

  assert.equal(totals.linesCount, 2)
  assert.equal(totals.excludedCount, 1)
  assert.equal(totals.totalHours, 14.5)
  assert.equal(totals.totalAmount, 45500)
})

test('recalcBillingTotals: правка цены меняет итог', () => {
  const drafts = createBillingLineDrafts(PREVIEW_LINES)
  drafts[0] = applyDraftRate(drafts[0], 2000)

  assert.equal(recalcBillingTotals(drafts).totalAmount, 53000)
})

test('recalcBillingTotals: без строк выставлять нечего', () => {
  const drafts = createBillingLineDrafts(PREVIEW_LINES).map(draft => toggleDraftExcluded(draft, true))
  const totals = recalcBillingTotals(drafts)

  assert.equal(totals.linesCount, 0)
  assert.equal(totals.totalAmount, 0)
  assert.equal(totals.issuable, false)
})

test('recalcBillingTotals: нулевая сумма не даёт выставить документ', () => {
  const drafts = createBillingLineDrafts([{ project_id: '1', title: 'Без ставки', hours: 4, rate: 0, amount: 0 }])

  assert.equal(recalcBillingTotals(drafts).issuable, false)
})

test('describeZeroAmountBlock: непустой документ с нулевой суммой — причина есть', () => {
  const drafts = createBillingLineDrafts([{ project_id: '1', title: 'Без ставки', hours: 4, rate: 0, amount: 0 }])
  const reason = describeZeroAmountBlock(recalcBillingTotals(drafts))

  assert.ok(reason)
  assert.match(reason as string, /0 ₽/)
  assert.match(reason as string, /ставку в карточке проекта/)
})

test('describeZeroAmountBlock: пустой документ (все строки исключены) — не эта причина', () => {
  const drafts = createBillingLineDrafts(PREVIEW_LINES).map(draft => toggleDraftExcluded(draft, true))

  assert.equal(describeZeroAmountBlock(recalcBillingTotals(drafts)), null)
})

test('describeZeroAmountBlock: сумма больше нуля — причины нет', () => {
  assert.equal(describeZeroAmountBlock(recalcBillingTotals(createBillingLineDrafts(PREVIEW_LINES))), null)
})

test('buildBillingLinesPayload: исключённые строки не уходят на сервер', () => {
  const drafts = createBillingLineDrafts(PREVIEW_LINES)
  drafts[1] = toggleDraftExcluded(drafts[1])
  drafts[0] = applyDraftTitle(drafts[0], 'Работы по договору')

  const payload = buildBillingLinesPayload(drafts)

  assert.equal(payload.length, 2)
  assert.equal(payload[0].title, 'Работы по договору')
  assert.equal(payload[0].sort, 10)
  assert.equal(payload[1].sort, 20)
  assert.deepEqual(payload.map(line => line.project_id), ['10', '12'])
})

test('hasDraftEdits: пометка «строки изменены вручную» зажигается на любой правке', () => {
  const drafts = createBillingLineDrafts(PREVIEW_LINES)

  assert.equal(hasDraftEdits(drafts), false)
  assert.equal(hasDraftEdits([toggleDraftExcluded(drafts[0]), drafts[1]]), true)
  assert.equal(hasDraftEdits([applyDraftRate(drafts[0], 1), drafts[1]]), true)
  assert.equal(hasDraftEdits([applyDraftTitle(drafts[0], 'иначе'), drafts[1]]), true)
})
