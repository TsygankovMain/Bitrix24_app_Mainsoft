import test from 'node:test'
import assert from 'node:assert/strict'

import {
  BILLING_CANCEL_CONSEQUENCE,
  BILLING_CANCEL_REASON_MAX_LENGTH,
  BILLING_CANCEL_REASON_MIN_LENGTH,
  BILLING_CANCEL_TITLE,
  billingCancelBlockReason,
  billingCancelHeading,
  billingCancelReasonLeft,
  billingCancelledNotice,
  canDismissBillingCancel,
  canSubmitBillingCancel,
  normalizeBillingCancelReason,
  validateBillingCancelReason,
} from '../app/utils/billingCancel'

test('billingCancelHeading: номер документа попадает в заголовок', () => {
  assert.equal(billingCancelHeading('№ 12 от 01.09.2026'), 'Отменить документ № 12 от 01.09.2026')
})

test('billingCancelHeading: номера ещё нет — заголовок без него, а не с «undefined»', () => {
  assert.equal(billingCancelHeading(null), BILLING_CANCEL_TITLE)
  assert.equal(billingCancelHeading(undefined), BILLING_CANCEL_TITLE)
  assert.equal(billingCancelHeading('   '), BILLING_CANCEL_TITLE)
})

test('текст последствия говорит про освобождение списаний, а не «вы уверены?»', () => {
  assert.match(BILLING_CANCEL_CONSEQUENCE, /списания/i)
  assert.match(BILLING_CANCEL_CONSEQUENCE, /свободн/i)
})

test('normalizeBillingCancelReason: обрезает пробелы и режет по верхнему пределу', () => {
  assert.equal(normalizeBillingCancelReason('  ошиблись клиентом  '), 'ошиблись клиентом')
  assert.equal(normalizeBillingCancelReason(null), '')
  assert.equal(
    normalizeBillingCancelReason('я'.repeat(BILLING_CANCEL_REASON_MAX_LENGTH + 50)).length,
    BILLING_CANCEL_REASON_MAX_LENGTH
  )
})

test('validateBillingCancelReason: пустая причина не проходит', () => {
  assert.match(String(validateBillingCancelReason('')), /Укажите причину/)
  assert.match(String(validateBillingCancelReason('   ')), /Укажите причину/)
  assert.match(String(validateBillingCancelReason(null)), /Укажите причину/)
})

test('validateBillingCancelReason: «-» и «..» не причина, хотя сервер их принял бы', () => {
  assert.match(String(validateBillingCancelReason('-')), /коротк/i)
  assert.match(String(validateBillingCancelReason('..')), /коротк/i)
})

test('validateBillingCancelReason: ровно минимальная длина проходит', () => {
  assert.equal(validateBillingCancelReason('я'.repeat(BILLING_CANCEL_REASON_MIN_LENGTH)), null)
})

test('validateBillingCancelReason: слишком длинная причина не проходит', () => {
  const tooLong = 'я'.repeat(BILLING_CANCEL_REASON_MAX_LENGTH + 1)

  assert.match(String(validateBillingCancelReason(tooLong)), /сократите/i)
})

test('validateBillingCancelReason: нормальная причина принимается', () => {
  assert.equal(validateBillingCancelReason('ошиблись клиентом, счёт переоформляем'), null)
})

test('canSubmitBillingCancel: нужны и причина, и галочка', () => {
  assert.equal(canSubmitBillingCancel({ reason: 'ошиблись клиентом', confirmed: true, submitting: false }), true)
  assert.equal(canSubmitBillingCancel({ reason: 'ошиблись клиентом', confirmed: false, submitting: false }), false)
  assert.equal(canSubmitBillingCancel({ reason: '', confirmed: true, submitting: false }), false)
})

test('canSubmitBillingCancel: во время отправки повторное нажатие невозможно', () => {
  assert.equal(canSubmitBillingCancel({ reason: 'ошиблись клиентом', confirmed: true, submitting: true }), false)
})

test('billingCancelBlockReason: объясняет, чего не хватает', () => {
  assert.match(
    String(billingCancelBlockReason({ reason: '', confirmed: true, submitting: false })),
    /Укажите причину/
  )
  assert.match(
    String(billingCancelBlockReason({ reason: 'ошиблись клиентом', confirmed: false, submitting: false })),
    /Подтвердите/
  )
  assert.equal(billingCancelBlockReason({ reason: 'ошиблись клиентом', confirmed: true, submitting: false }), null)
})

test('billingCancelBlockReason: во время отправки не ругаемся — там своё состояние', () => {
  assert.equal(billingCancelBlockReason({ reason: '', confirmed: false, submitting: true }), null)
})

test('canDismissBillingCancel: пустую панель закрыть щелчком мимо можно', () => {
  assert.equal(canDismissBillingCancel({ reason: '', submitting: false }), true)
  assert.equal(canDismissBillingCancel({ reason: '   ', submitting: false }), true)
})

test('canDismissBillingCancel: набранное не теряем и отправку не прерываем', () => {
  assert.equal(canDismissBillingCancel({ reason: 'ош', submitting: false }), false)
  assert.equal(canDismissBillingCancel({ reason: '', submitting: true }), false)
})

test('billingCancelReasonLeft: остаток символов не уходит в минус', () => {
  assert.equal(billingCancelReasonLeft(''), BILLING_CANCEL_REASON_MAX_LENGTH)
  assert.equal(billingCancelReasonLeft('ошибка'), BILLING_CANCEL_REASON_MAX_LENGTH - 6)
  assert.equal(billingCancelReasonLeft('я'.repeat(BILLING_CANCEL_REASON_MAX_LENGTH + 10)), 0)
})

test('billingCancelledNotice: называет номер отменённого документа', () => {
  assert.match(billingCancelledNotice('№ 12'), /Документ № 12 отменён/)
  assert.match(billingCancelledNotice(null), /^Документ отменён/)
  assert.match(billingCancelledNotice(''), /списания освобождены/)
})
