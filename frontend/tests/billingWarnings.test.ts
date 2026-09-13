import test from 'node:test'
import assert from 'node:assert/strict'

import {
  describeBillingWarning,
  describeBillingWarnings,
  hasBlockingBillingWarning,
  splitBillingWarnings,
} from '../app/utils/billingWarnings'

test('describeBillingWarning: period_open объясняет риск и не блокирует', () => {
  const view = describeBillingWarning({ code: 'period_open' })

  assert.equal(view.code, 'period_open')
  assert.equal(view.title, 'Месяц не закрыт')
  assert.equal(view.blocking, false)
  assert.match(view.text, /настройка/)
})

test('describeBillingWarning: already_invoiced называет количество записей', () => {
  const view = describeBillingWarning({ code: 'already_invoiced', count: 3 })

  assert.match(view.text, /3 записи/)
  assert.equal(view.blocking, false)
})

test('describeBillingWarning: already_invoiced без количества тоже читается', () => {
  const view = describeBillingWarning({ code: 'already_invoiced' })

  assert.match(view.text, /Часть записей/)
})

test('describeBillingWarning: no_rate подсказывает, что делать', () => {
  const view = describeBillingWarning({ code: 'no_rate', count: 1 })

  assert.equal(view.title, 'Нет ставки')
  assert.match(view.text, /1 запись/)
  assert.match(view.text, /карточке проекта|ставку в проекте/)
  assert.equal(view.blocking, false)
})

test('describeBillingWarning: mixed_companies — единственное блокирующее', () => {
  const view = describeBillingWarning({ code: 'mixed_companies' })

  assert.equal(view.blocking, true)
  assert.match(view.text, /одного клиента/)
})

test('describeBillingWarning: серверный текст важнее нашего шаблона', () => {
  const view = describeBillingWarning({ code: 'period_open', message: 'Август не закрыт' })

  assert.equal(view.text, 'Август не закрыт')
  assert.equal(view.title, 'Месяц не закрыт')
})

test('describeBillingWarning: незнакомый код не молчит и не блокирует', () => {
  const unknown = describeBillingWarning({ code: 'future_code' })

  assert.equal(unknown.code, 'future_code')
  assert.equal(unknown.blocking, false)
  assert.match(unknown.text, /future_code/)

  const withMessage = describeBillingWarning({ code: 'future_code', message: 'Что-то новое' })
  assert.equal(withMessage.text, 'Что-то новое')
})

test('describeBillingWarning: предупреждение без кода всё равно показывается', () => {
  const view = describeBillingWarning({})

  assert.equal(view.code, 'unknown')
  assert.match(view.text, /без кода/)
})

test('describeBillingWarnings: не массив — пустой список', () => {
  assert.deepEqual(describeBillingWarnings(null), [])
  assert.deepEqual(describeBillingWarnings(undefined), [])
})

test('hasBlockingBillingWarning: блокер находится среди мягких', () => {
  assert.equal(hasBlockingBillingWarning([{ code: 'period_open' }, { code: 'mixed_companies' }]), true)
  assert.equal(hasBlockingBillingWarning([{ code: 'period_open' }, { code: 'no_rate' }]), false)
  assert.equal(hasBlockingBillingWarning([]), false)
})

test('splitBillingWarnings: блокеры и предупреждения показываются раздельно', () => {
  const { blockers, notices } = splitBillingWarnings([
    { code: 'period_open' },
    { code: 'mixed_companies' },
    { code: 'already_invoiced', count: 2 },
  ])

  assert.deepEqual(blockers.map(item => item.code), ['mixed_companies'])
  assert.deepEqual(notices.map(item => item.code), ['period_open', 'already_invoiced'])
})

test('describeBillingWarning: флаг blocking с сервера главнее нашей таблицы кодов', () => {
  assert.equal(describeBillingWarning({ code: 'period_open', blocking: true }).blocking, true)
  assert.equal(describeBillingWarning({ code: 'mixed_companies', blocking: false }).blocking, false)
  assert.equal(describeBillingWarning({ code: 'future_code', blocking: true }).blocking, true)
})

test('describeBillingWarning: без флага решает код — mixed_companies блокирует, остальные нет', () => {
  assert.equal(describeBillingWarning({ code: 'mixed_companies' }).blocking, true)
  assert.equal(describeBillingWarning({ code: 'no_rate' }).blocking, false)
})
