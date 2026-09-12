import test from 'node:test'
import assert from 'node:assert/strict'

import {
  NBSP,
  billingDocumentNumber,
  billingStatusLabel,
  formatBillingAmount,
  formatBillingDate,
  formatBillingHours,
  formatBillingHoursWithUnit,
  formatBillingMoney,
  formatBillingPeriod,
  formatDaysRu,
  formatRecordsRu,
  pluralizeRu,
} from '../app/utils/billingFormat'

test('formatBillingAmount: разряды неразрывным пробелом, копейки через запятую', () => {
  assert.equal(formatBillingAmount(1234567.5), `1${NBSP}234${NBSP}567,50`)
  assert.equal(formatBillingAmount(0), '0,00')
  assert.equal(formatBillingAmount(999), '999,00')
  assert.equal(formatBillingAmount(1000), `1${NBSP}000,00`)
})

test('formatBillingAmount: строку с пробелами и запятой тоже понимаем', () => {
  assert.equal(formatBillingAmount('1 234,5'), `1${NBSP}234,50`)
  assert.equal(formatBillingAmount('12.34'), '12,34')
})

test('formatBillingAmount: мусор — это ноль, а не NaN на экране', () => {
  assert.equal(formatBillingAmount(undefined), '0,00')
  assert.equal(formatBillingAmount(null), '0,00')
  assert.equal(formatBillingAmount('не число'), '0,00')
  assert.equal(formatBillingAmount(Number.NaN), '0,00')
})

test('formatBillingAmount: минус выносится перед разрядами', () => {
  assert.equal(formatBillingAmount(-1234.5), `−1${NBSP}234,50`)
})

test('formatBillingMoney: рубль символом, неизвестная валюта — кодом', () => {
  assert.equal(formatBillingMoney(1500), `1${NBSP}500,00${NBSP}₽`)
  assert.equal(formatBillingMoney(1500, 'RUB'), `1${NBSP}500,00${NBSP}₽`)
  assert.equal(formatBillingMoney(1500, 'KZT'), `1${NBSP}500,00${NBSP}KZT`)
  assert.equal(formatBillingMoney(1500, null), `1${NBSP}500,00${NBSP}₽`)
})

test('formatBillingHours: целое остаётся целым, дробное — с одним знаком', () => {
  assert.equal(formatBillingHours(8), '8')
  assert.equal(formatBillingHours(7.5), '7,5')
  assert.equal(formatBillingHours(7.46), '7,5')
  assert.equal(formatBillingHours(1200), `1${NBSP}200`)
  assert.equal(formatBillingHoursWithUnit(8), `8${NBSP}ч`)
})

test('formatBillingDate: ISO превращается в ДД.ММ.ГГГГ, мусор возвращается как есть', () => {
  assert.equal(formatBillingDate('2026-09-12'), '12.09.2026')
  assert.equal(formatBillingDate('2026-09-12T10:30:00Z'), '12.09.2026')
  assert.equal(formatBillingDate(''), '')
  assert.equal(formatBillingDate(null), '')
  assert.equal(formatBillingDate('вчера'), 'вчера')
})

test('formatBillingPeriod: ровный месяц пишется словом', () => {
  assert.equal(formatBillingPeriod('2026-09-01', '2026-09-30'), 'сентябрь 2026')
  assert.equal(formatBillingPeriod('2026-02-01', '2026-02-28'), 'февраль 2026')
})

test('formatBillingPeriod: високосный февраль — тоже ровный месяц', () => {
  assert.equal(formatBillingPeriod('2028-02-01', '2028-02-29'), 'февраль 2028')
})

test('formatBillingPeriod: неполный месяц показывается двумя датами', () => {
  assert.equal(formatBillingPeriod('2026-09-01', '2026-09-15'), '01.09.2026 — 15.09.2026')
  assert.equal(formatBillingPeriod('2026-08-15', '2026-09-14'), '15.08.2026 — 14.09.2026')
})

test('formatBillingPeriod: половина периода не выдаётся за целый', () => {
  assert.equal(formatBillingPeriod('2026-09-01', ''), '01.09.2026')
  assert.equal(formatBillingPeriod('', ''), '')
})

test('pluralizeRu: 1 день, 2 дня, 5 дней, 11 дней, 21 день', () => {
  const forms: [string, string, string] = ['день', 'дня', 'дней']

  assert.equal(pluralizeRu(1, forms), 'день')
  assert.equal(pluralizeRu(2, forms), 'дня')
  assert.equal(pluralizeRu(4, forms), 'дня')
  assert.equal(pluralizeRu(5, forms), 'дней')
  assert.equal(pluralizeRu(11, forms), 'дней')
  assert.equal(pluralizeRu(14, forms), 'дней')
  assert.equal(pluralizeRu(21, forms), 'день')
  assert.equal(pluralizeRu(0, forms), 'дней')
})

test('formatDaysRu и formatRecordsRu: число вместе со словом', () => {
  assert.equal(formatDaysRu(1), '1 день')
  assert.equal(formatDaysRu(3), '3 дня')
  assert.equal(formatDaysRu(14), '14 дней')
  assert.equal(formatRecordsRu(1), '1 запись')
  assert.equal(formatRecordsRu(3), '3 записи')
  assert.equal(formatRecordsRu(17), '17 записей')
})

test('billingStatusLabel: статусы по-русски, чужой статус не притворяется своим', () => {
  assert.equal(billingStatusLabel('issued'), 'Выставлен')
  assert.equal(billingStatusLabel('cancelled'), 'Отменён')
  assert.equal(billingStatusLabel('draft'), 'Неизвестен')
  assert.equal(billingStatusLabel(null), 'Неизвестен')
})

test('billingDocumentNumber: номер портала важнее внутреннего id', () => {
  assert.equal(billingDocumentNumber({ crm_account_number: 'СЧ-118', id: 7 }), 'СЧ-118')
  assert.equal(billingDocumentNumber({ crm_account_number: '', id: 7 }), '#7')
  assert.equal(billingDocumentNumber({ id: null }), '—')
  assert.equal(billingDocumentNumber(null), '—')
})
