import test from 'node:test'
import assert from 'node:assert/strict'

import {
  formatPlanDate,
  nextPlanDay,
  PRO_CTA_LABEL,
  PRO_PLAN_LABEL,
  PRO_ROUTE,
  proPriceText,
  proRoute,
} from '../app/utils/proPlan'

test('тариф называется Pro, кнопка — «Купить Pro», цена по умолчанию 3000 ₽ за портал', () => {
  assert.equal(PRO_PLAN_LABEL, 'Pro')
  assert.equal(PRO_CTA_LABEL, 'Купить Pro')
  assert.equal(proPriceText(), '3000\u00A0₽ в месяц за портал')
})

test('proPriceText: цена с сервера побеждает, мусор — цена по умолчанию', () => {
  assert.equal(proPriceText(2500), '2500\u00A0₽ в месяц за портал')
  assert.equal(proPriceText('4000'), '4000\u00A0₽ в месяц за портал')
  assert.equal(proPriceText(0), '3000\u00A0₽ в месяц за портал')
  assert.equal(proPriceText('нет'), '3000\u00A0₽ в месяц за портал')
})

test('форма запроса счёта живёт по адресу /pro', () => {
  assert.equal(PRO_ROUTE, '/pro')
})

test('proRoute: код функции уходит параметром, чужое значение отбрасывается', () => {
  assert.equal(proRoute('bdds'), '/pro?feature=bdds')
  assert.equal(proRoute('roles'), '/pro?feature=roles')
  assert.equal(proRoute(''), '/pro')
  assert.equal(proRoute('x&y=1'), '/pro')
  assert.equal(proRoute(null), '/pro')
})

test('formatPlanDate и nextPlanDay: даты тарифа в человеческом виде', () => {
  assert.equal(formatPlanDate('2026-10-31'), '31.10.2026')
  assert.equal(formatPlanDate('2026-10-31T00:00:00Z'), '31.10.2026')
  assert.equal(formatPlanDate(null), '')
  assert.equal(nextPlanDay('2026-12-31'), '2027-01-01')
  assert.equal(nextPlanDay('2026-02-28'), '2026-03-01')
  assert.equal(nextPlanDay('мусор'), null)
})
