import test from 'node:test'
import assert from 'node:assert/strict'

import {
  findOpenMonths,
  listBillingMonths,
  resolveBillingEmptyReason,
} from '../app/utils/billingEmptyReason'

const SEPTEMBER = {
  dateFrom: '2026-09-01',
  dateTo: '2026-09-30',
  onlyClosedPeriods: true,
  allowOpenPeriod: false,
}

test('listBillingMonths: один месяц — один элемент с русским названием', () => {
  const months = listBillingMonths('2026-09-01', '2026-09-30')

  assert.deepEqual(months.map(item => item.key), ['2026-09'])
  assert.equal(months[0]?.title, 'сентябрь 2026')
})

test('listBillingMonths: период через границу года', () => {
  const months = listBillingMonths('2025-11-15', '2026-02-03')

  assert.deepEqual(months.map(item => item.key), ['2025-11', '2025-12', '2026-01', '2026-02'])
})

test('listBillingMonths: перевёрнутый и битый период — пустой список', () => {
  assert.deepEqual(listBillingMonths('2026-09-30', '2026-09-01'), [])
  assert.deepEqual(listBillingMonths('', '2026-09-30'), [])
  assert.deepEqual(listBillingMonths('не дата', 'тоже нет'), [])
})

test('findOpenMonths: месяц без записи в /api/periods считается незакрытым', () => {
  const months = listBillingMonths('2026-08-01', '2026-09-30')
  const open = findOpenMonths(months, [{ year: 2026, month: 8, closed: true }])

  assert.deepEqual(open.map(item => item.key), ['2026-09'])
})

test('findOpenMonths: список не загрузился — не знаем ничего', () => {
  const months = listBillingMonths('2026-09-01', '2026-09-30')

  assert.deepEqual(findOpenMonths(months, null), [])
})

test('resolveBillingEmptyReason: текущий месяц не закрыт — это и есть причина пустоты', () => {
  const reason = resolveBillingEmptyReason({
    ...SEPTEMBER,
    periods: [{ year: 2026, month: 9, closed: false }],
  })

  assert.equal(reason.code, 'period_open')
  assert.match(reason.title, /сентябрь 2026/)
  assert.match(reason.title, /выставлять по умолчанию нельзя/)
  assert.match(reason.text, /только закрытые месяцы/)
})

test('resolveBillingEmptyReason: настройка запрещает открытый период — снять галочку не предлагаем', () => {
  const reason = resolveBillingEmptyReason({
    ...SEPTEMBER,
    allowOpenPeriod: false,
    periods: [{ year: 2026, month: 9, closed: false }],
  })

  assert.deepEqual(reason.actions.map(action => action.id), ['close-period'])
  assert.equal(reason.actions[0]?.to, '/settings/periods')
  assert.match(reason.text, /выключена/)
})

test('resolveBillingEmptyReason: настройка разрешает — обе кнопки на месте', () => {
  const reason = resolveBillingEmptyReason({
    ...SEPTEMBER,
    allowOpenPeriod: true,
    periods: [{ year: 2026, month: 9, closed: false }],
  })

  assert.deepEqual(reason.actions.map(action => action.id), ['drop-closed-filter', 'close-period'])
  assert.match(reason.text, /включена/)
})

test('resolveBillingEmptyReason: несколько незакрытых месяцев названы во множественном числе', () => {
  const reason = resolveBillingEmptyReason({
    dateFrom: '2026-08-01',
    dateTo: '2026-09-30',
    onlyClosedPeriods: true,
    allowOpenPeriod: false,
    periods: [],
  })

  assert.equal(reason.code, 'period_open')
  assert.match(reason.title, /Месяцы август 2026, сентябрь 2026 не закрыты/)
})

test('resolveBillingEmptyReason: галочка снята — незакрытый месяц причиной уже не считается', () => {
  const reason = resolveBillingEmptyReason({
    ...SEPTEMBER,
    onlyClosedPeriods: false,
    periods: [{ year: 2026, month: 9, closed: false }],
  })

  assert.equal(reason.code, 'no_hours')
})

test('resolveBillingEmptyReason: всё уже выставлено — ссылка в реестр', () => {
  const reason = resolveBillingEmptyReason({
    dateFrom: '2026-08-01',
    dateTo: '2026-08-31',
    onlyClosedPeriods: true,
    allowOpenPeriod: false,
    periods: [{ year: 2026, month: 8, closed: true }],
    warnings: [{ code: 'already_invoiced', count: 33 }],
  })

  assert.equal(reason.code, 'all_invoiced')
  assert.match(reason.text, /33 записи/)
  assert.match(reason.text, /август 2026/)
  assert.deepEqual(reason.actions.map(action => action.to), ['/finance/billing'])
})

test('resolveBillingEmptyReason: закрытый месяц перевешивает «уже выставлено» только частично', () => {
  // Один месяц закрыт, второй нет: часть отбора могла отработать, поэтому
  // сначала объясняем «уже выставлено», а не незакрытый месяц.
  const reason = resolveBillingEmptyReason({
    dateFrom: '2026-08-01',
    dateTo: '2026-09-30',
    onlyClosedPeriods: true,
    allowOpenPeriod: false,
    periods: [{ year: 2026, month: 8, closed: true }],
    warnings: [{ code: 'already_invoiced', count: 5 }],
  })

  assert.equal(reason.code, 'all_invoiced')
})

test('resolveBillingEmptyReason: частично открытый период без «уже выставлено» — про месяц', () => {
  const reason = resolveBillingEmptyReason({
    dateFrom: '2026-08-01',
    dateTo: '2026-09-30',
    onlyClosedPeriods: true,
    allowOpenPeriod: false,
    periods: [{ year: 2026, month: 8, closed: true }],
  })

  assert.equal(reason.code, 'period_open')
  assert.match(reason.title, /сентябрь 2026/)
})

test('resolveBillingEmptyReason: часов просто нет — называем клиента и сузившие фильтры', () => {
  const reason = resolveBillingEmptyReason({
    dateFrom: '2026-08-01',
    dateTo: '2026-08-31',
    onlyClosedPeriods: true,
    allowOpenPeriod: false,
    periods: [{ year: 2026, month: 8, closed: true }],
    companyName: 'ООО «Ромашка»',
    filters: { billableOnly: true, projectIds: ['1', '2'], employeeIds: [], taskIds: ['9483'] },
  })

  assert.equal(reason.code, 'no_hours')
  assert.match(reason.text, /ООО «Ромашка»/)
  assert.match(reason.text, /только оплачиваемые/)
  assert.match(reason.text, /проекты \(2\)/)
  assert.match(reason.text, /задачи \(1\)/)
  assert.equal(reason.actions.length, 0)
})

test('resolveBillingEmptyReason: без сузивших фильтров текст всё равно подсказывает, где искать', () => {
  const reason = resolveBillingEmptyReason({
    dateFrom: '2026-08-01',
    dateTo: '2026-08-31',
    onlyClosedPeriods: true,
    allowOpenPeriod: false,
    periods: [{ year: 2026, month: 8, closed: true }],
    filters: { billableOnly: false, projectIds: [], employeeIds: [], taskIds: [] },
  })

  assert.equal(reason.code, 'no_hours')
  assert.match(reason.text, /другом месяце|другого заказчика/)
})

test('resolveBillingEmptyReason: список периодов не загрузился — не выдумываем закрытость', () => {
  const reason = resolveBillingEmptyReason({ ...SEPTEMBER, periods: null })

  assert.equal(reason.code, 'no_hours')
})
