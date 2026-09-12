import test from 'node:test'
import assert from 'node:assert/strict'

import {
  BILLING_FEATURE_CODE,
  isBillingManager,
  normalizeAccountantIds,
  normalizeFeatureState,
  parsePortalFeatures,
  readPortalFeature,
  resolveBillingAccess,
  resolveBillingUiPermissions,
  trialBadgeText,
  trialDaysLeft,
} from '../app/utils/billingFeature'
import { PAID_FEATURE_BADGE } from '../app/utils/paidFeatures'

test('normalizeFeatureState: понятны только три состояния, остальное — выключено', () => {
  assert.equal(normalizeFeatureState('on'), 'on')
  assert.equal(normalizeFeatureState('TRIAL'), 'trial')
  assert.equal(normalizeFeatureState('off'), 'off')
  assert.equal(normalizeFeatureState('enabled'), 'off')
  assert.equal(normalizeFeatureState(undefined), 'off')
  assert.equal(normalizeFeatureState(1), 'off')
})

test('parsePortalFeatures: ответ сервера превращается в состояния по кодам', () => {
  const features = parsePortalFeatures({
    billing: { state: 'trial', trial_until: '2026-09-30' },
    bdds: { state: 'off', trial_until: null },
  })

  assert.equal(features.billing.state, 'trial')
  assert.equal(features.billing.trialUntil, '2026-09-30')
  assert.equal(features.bdds.state, 'off')
  assert.equal(features.bdds.trialUntil, null)
})

test('parsePortalFeatures: дата с временем обрезается до дня, мусор не роняет разбор', () => {
  const features = parsePortalFeatures({
    billing: { state: 'trial', trial_until: '2026-09-30T23:59:59Z' },
    broken: null,
  })

  assert.equal(features.billing.trialUntil, '2026-09-30')
  assert.equal(features.broken.state, 'off')
  assert.deepEqual(parsePortalFeatures(null), {})
  assert.deepEqual(parsePortalFeatures('нет'), {})
})

test('readPortalFeature: незнакомая функция считается выключенной', () => {
  assert.deepEqual(readPortalFeature({}, BILLING_FEATURE_CODE), { state: 'off', trialUntil: null })
  assert.deepEqual(readPortalFeature(null, BILLING_FEATURE_CODE), { state: 'off', trialUntil: null })
})

test('trialDaysLeft: считаем календарные дни, время суток на результат не влияет', () => {
  assert.equal(trialDaysLeft('2026-09-30', new Date(2026, 8, 12, 9, 0)), 18)
  assert.equal(trialDaysLeft('2026-09-30', new Date(2026, 8, 12, 23, 59)), 18)
  assert.equal(trialDaysLeft('2026-09-12', new Date(2026, 8, 12, 0, 1)), 0)
  assert.equal(trialDaysLeft('2026-09-11', new Date(2026, 8, 12)), -1)
})

test('trialDaysLeft: без даты — null, а не ноль (ноль означал бы «последний день»)', () => {
  assert.equal(trialDaysLeft(null, new Date(2026, 8, 12)), null)
  assert.equal(trialDaysLeft('', new Date(2026, 8, 12)), null)
  assert.equal(trialDaysLeft('скоро', new Date(2026, 8, 12)), null)
})

test('trialBadgeText: текст бейджа склоняется и различает последний день и истечение', () => {
  assert.equal(trialBadgeText(18), 'пробный, осталось 18 дней')
  assert.equal(trialBadgeText(3), 'пробный, осталось 3 дня')
  assert.equal(trialBadgeText(1), 'пробный, осталось 1 день')
  assert.equal(trialBadgeText(0), 'пробный, последний день')
  assert.equal(trialBadgeText(-2), 'пробный период истёк')
  assert.equal(trialBadgeText(null), 'пробный период')
})

test('resolveBillingAccess: state = on открывает экран без бейджа', () => {
  const access = resolveBillingAccess({
    features: parsePortalFeatures({ billing: { state: 'on' } }),
    flagEnabled: true,
  })

  assert.equal(access.enabled, true)
  assert.equal(access.locked, false)
  assert.equal(access.badge, null)
  assert.equal(access.hint, null)
  assert.equal(access.unknown, false)
})

test('resolveBillingAccess: state = trial открывает экран и показывает остаток дней', () => {
  const access = resolveBillingAccess({
    features: parsePortalFeatures({ billing: { state: 'trial', trial_until: '2026-09-17' } }),
    flagEnabled: true,
    now: new Date(2026, 8, 12),
  })

  assert.equal(access.enabled, true)
  assert.equal(access.trialDaysLeft, 5)
  assert.equal(access.badge, 'пробный, осталось 5 дней')
})

test('resolveBillingAccess: state = off оставляет замок и подсказку «к администратору»', () => {
  const access = resolveBillingAccess({
    features: parsePortalFeatures({ billing: { state: 'off' } }),
    flagEnabled: true,
  })

  assert.equal(access.enabled, false)
  assert.equal(access.locked, true)
  assert.equal(access.badge, PAID_FEATURE_BADGE)
  assert.match(access.hint || '', /администратору/)
})

test('resolveBillingAccess: фронтовый флаг — аварийный выключатель, открыть функцию он не может', () => {
  const enabledByServer = parsePortalFeatures({ billing: { state: 'on' } })

  assert.equal(resolveBillingAccess({ features: enabledByServer, flagEnabled: false }).enabled, false)
  assert.equal(
    resolveBillingAccess({ features: parsePortalFeatures({ billing: { state: 'off' } }), flagEnabled: true }).enabled,
    false
  )
})

test('resolveBillingAccess: ответа сервера ещё нет — функция закрыта, но помечена как неизвестная', () => {
  const access = resolveBillingAccess({ features: null, flagEnabled: true })

  assert.equal(access.unknown, true)
  assert.equal(access.enabled, false)
  assert.equal(access.state, 'off')
})

test('normalizeAccountantIds: числа и строки сравнимы, пустое и дубли отбрасываются', () => {
  assert.deepEqual(normalizeAccountantIds([11, '12', ' 13 ', '', null, '12']), ['11', '12', '13'])
  assert.deepEqual(normalizeAccountantIds('11'), [])
  assert.deepEqual(normalizeAccountantIds(undefined), [])
})

test('isBillingManager: админ портала может всегда', () => {
  assert.equal(isBillingManager({ isAdmin: true, userId: 999, accountantIds: [] }), true)
})

test('isBillingManager: сотрудник из списка «Бухгалтерия» опознаётся и по числовому id', () => {
  assert.equal(isBillingManager({ isAdmin: false, userId: 11, accountantIds: ['11'] }), true)
  assert.equal(isBillingManager({ isAdmin: false, userId: '11', accountantIds: [11] }), true)
  assert.equal(isBillingManager({ isAdmin: false, userId: 12, accountantIds: ['11'] }), false)
  assert.equal(isBillingManager({ isAdmin: false, userId: null, accountantIds: ['11'] }), false)
})

test('resolveBillingUiPermissions: без подписки остаются реестр и отмена', () => {
  const permissions = resolveBillingUiPermissions({ enabled: false }, true)

  assert.equal(permissions.canViewRegistry, true)
  assert.equal(permissions.canIssue, false)
  assert.equal(permissions.canPrintAct, false)
  assert.equal(permissions.canCancel, true)
})

test('resolveBillingUiPermissions: не бухгалтер видит реестр и ничего больше', () => {
  const permissions = resolveBillingUiPermissions({ enabled: true }, false)

  assert.equal(permissions.canViewRegistry, true)
  assert.equal(permissions.canIssue, false)
  assert.equal(permissions.canPrintAct, false)
  assert.equal(permissions.canCancel, false)
})

test('resolveBillingUiPermissions: бухгалтер при включённой подписке может всё', () => {
  const permissions = resolveBillingUiPermissions({ enabled: true }, true)

  assert.equal(permissions.canIssue, true)
  assert.equal(permissions.canPrintAct, true)
  assert.equal(permissions.canCancel, true)
})
