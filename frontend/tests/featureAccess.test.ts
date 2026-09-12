import test from 'node:test'
import assert from 'node:assert/strict'

import {
  GRACE_BADGE,
  parsePortalFeatures,
  READ_ONLY_BADGE,
  resolveFeatureAccess,
} from '../app/utils/featureAccess'
import { resolveBillingAccess, resolveBillingUiPermissions } from '../app/utils/billingFeature'
import { resolveBddsAccess } from '../app/utils/bddsFeature'
import { describeBddsError } from '../app/utils/bddsErrors'
import { describeBillingError } from '../app/utils/billingErrors'
import { isFinanceFeatureId, isPaidFeatureId, resolvePaidFeatureState } from '../app/utils/paidFeatures'

const NOW = new Date(2026, 8, 12, 10, 0)

function access(payload: Record<string, unknown>, code = 'bdds', flagEnabled = true) {
  return resolveFeatureAccess({
    features: parsePortalFeatures({ [code]: payload }),
    code,
    title: 'БДДС по проектам',
    flagEnabled,
    now: NOW,
  })
}

test('parsePortalFeatures: новые поля тарифа разбираются, даты обрезаются до дня', () => {
  const features = parsePortalFeatures({
    billing: {
      state: 'on', access: 'full', status: 'grace',
      paid_until: '2026-09-10', grace_until: '2026-09-17T00:00:00', price_month_rub: 2500,
    },
  })

  assert.deepEqual(features.billing, {
    state: 'on',
    trialUntil: null,
    access: 'full',
    status: 'grace',
    paidUntil: '2026-09-10',
    graceUntil: '2026-09-17',
    priceMonthRub: 2500,
    restrictionsActive: true,
  })
})

test('parsePortalFeatures: старый ответ без access понятен по state', () => {
  const features = parsePortalFeatures({ bdds: { state: 'on' }, billing: { state: 'off' }, roles: { state: 'trial' } })

  assert.equal(features.bdds.access, 'full')
  assert.equal(features.bdds.status, 'active')
  assert.equal(features.billing.access, 'none')
  assert.equal(features.roles.status, 'trial')
  assert.equal(features.bdds.priceMonthRub, 3000)
})

test('parsePortalFeatures: незнакомый access — по state, в строгую сторону', () => {
  assert.equal(parsePortalFeatures({ bdds: { state: 'off', access: 'god' } }).bdds.access, 'none')
})

test('действующий Pro — экран открыт, запись разрешена, плашки и бейджа нет', () => {
  const view = access({ state: 'on', access: 'full', status: 'active', paid_until: '2026-12-31' })

  assert.equal(view.enabled, true)
  assert.equal(view.canWrite, true)
  assert.equal(view.readOnly, false)
  assert.equal(view.locked, false)
  assert.equal(view.badge, null)
  assert.equal(view.notice, null)
})

test('Pro закончился — экран открыт на чтение, запись закрыта, бейдж и плашка с датой', () => {
  const view = access({
    state: 'off', access: 'read_only', status: 'expired',
    paid_until: '2026-08-31', grace_until: '2026-09-07',
  })

  assert.equal(view.enabled, true)
  assert.equal(view.canWrite, false)
  assert.equal(view.readOnly, true)
  assert.equal(view.locked, false)
  assert.equal(view.badge, READ_ONLY_BADGE)
  assert.equal(view.notice?.tone, 'danger')
  assert.match(view.notice?.title || '', /только просмотр/)
  assert.match(view.notice?.text || '', /закрыты с 08\.09\.2026/)
  assert.match(view.notice?.text || '', /Просмотр и выгрузки работают/)
  assert.match(view.notice?.text || '', /3000\u00A0₽ в месяц за портал/)
})

test('истёкший пробный — тоже «только чтение», дата закрытия — день после пробного', () => {
  const view = access({ state: 'off', access: 'read_only', status: 'expired', trial_until: '2026-09-01' })

  assert.equal(view.readOnly, true)
  assert.match(view.notice?.text || '', /закрыты с 02\.09\.2026/)
})

test('грейс — всё работает, бейдж «продлите Pro» и предупреждение до какого числа', () => {
  const view = access({
    state: 'on', access: 'full', status: 'grace', paid_until: '2026-09-10', grace_until: '2026-09-17',
  })

  assert.equal(view.canWrite, true)
  assert.equal(view.badge, GRACE_BADGE)
  assert.equal(view.notice?.tone, 'warning')
  assert.match(view.notice?.text || '', /до 17\.09\.2026 включительно/)
})

test('пробный — бейдж с днями, плашка только в последние три дня', () => {
  const far = access({ state: 'trial', access: 'full', status: 'trial', trial_until: '2026-09-30' })
  const near = access({ state: 'trial', access: 'full', status: 'trial', trial_until: '2026-09-14' })
  const last = access({ state: 'trial', access: 'full', status: 'trial', trial_until: '2026-09-12' })

  assert.equal(far.badge, 'пробный, осталось 18 дней')
  assert.equal(far.notice, null)
  assert.match(near.notice?.title || '', /заканчивается 14\.09\.2026/)
  assert.match(last.notice?.title || '', /последний день/)
})

test('без тарифа — замок, бейдж Pro, цена; плашки нет', () => {
  const view = access({ state: 'off', access: 'none', status: 'off' })

  assert.equal(view.locked, true)
  assert.equal(view.enabled, false)
  assert.equal(view.canWrite, false)
  assert.equal(view.badge, 'Pro')
  assert.equal(view.notice, null)
  assert.equal(view.priceText, '3000\u00A0₽ в месяц за портал')
})

test('аварийный выключатель закрывает и «только чтение»', () => {
  const view = access({ state: 'off', access: 'read_only', status: 'expired' }, 'bdds', false)

  assert.equal(view.locked, true)
  assert.equal(view.readOnly, false)
})

test('ролевая модель читается тем же разбором по коду roles', () => {
  const view = resolveFeatureAccess({
    features: parsePortalFeatures({ roles: { state: 'on', access: 'full', status: 'active' } }),
    code: 'roles',
    title: 'Ролевая модель',
    flagEnabled: true,
  })

  assert.equal(view.canWrite, true)
  assert.equal(isPaidFeatureId('roles'), true)
  assert.equal(isFinanceFeatureId('roles'), false)
  assert.equal(resolvePaidFeatureState('roles', false).to, '/pro?feature=roles')
})

test('роли после окончания Pro: менять нельзя, но ограничения продолжают действовать', () => {
  const view = resolveFeatureAccess({
    features: parsePortalFeatures({
      roles: { state: 'off', access: 'read_only', status: 'expired', restrictions_active: true },
    }),
    code: 'roles',
    title: 'Ролевая модель',
    flagEnabled: true,
  })

  assert.equal(view.canWrite, false)
  assert.equal(view.restrictionsActive, true)
  assert.match(view.notice?.title || '', /роли не меняются/)
  assert.match(view.notice?.text || '', /ограничения продолжают действовать/)
})

test('роли: аварийный выключатель закрывает экран, но не снимает ограничения', () => {
  const view = resolveFeatureAccess({
    features: parsePortalFeatures({ roles: { state: 'on', access: 'full', status: 'active' } }),
    code: 'roles',
    title: 'Ролевая модель',
    flagEnabled: false,
  })

  assert.equal(view.locked, true)
  assert.equal(view.restrictionsActive, true)
})

test('роли без Pro и выключенные — ограничений нет', () => {
  const none = resolveFeatureAccess({ features: parsePortalFeatures({}), code: 'roles', title: 'Ролевая модель', flagEnabled: true })
  const off = resolveFeatureAccess({
    features: parsePortalFeatures({ roles: { state: 'off', access: 'none', status: 'off', restrictions_active: false } }),
    code: 'roles',
    title: 'Ролевая модель',
    flagEnabled: true,
  })

  assert.equal(none.restrictionsActive, false)
  assert.equal(off.restrictionsActive, false)
})

test('счёт после окончания Pro: реестр и отмена есть, выставления и печати нет', () => {
  const billing = resolveBillingAccess({
    features: parsePortalFeatures({ billing: { state: 'off', access: 'read_only', status: 'expired' } }),
    flagEnabled: true,
  })
  const permissions = resolveBillingUiPermissions(billing, true)

  assert.equal(billing.enabled, true)
  assert.deepEqual(permissions, { canViewRegistry: true, canIssue: false, canPrintAct: false, canCancel: true })
})

test('БДДС после окончания Pro: экран открыт на чтение', () => {
  const bdds = resolveBddsAccess({
    features: parsePortalFeatures({ bdds: { state: 'off', access: 'read_only', status: 'expired' } }),
    flagEnabled: true,
  })

  assert.equal(bdds.enabled, true)
  assert.equal(bdds.canWrite, false)
})

function httpError(status: number, payload: Record<string, unknown> = {}) {
  return { response: { status, _data: payload }, status, data: payload }
}

test('отказ сервера reason=expired: не «функция выключена», а «Pro закончился»', () => {
  const bdds = describeBddsError(httpError(403, { code: 'feature_disabled', reason: 'expired', feature: 'bdds' }))
  const billing = describeBillingError(httpError(403, { code: 'feature_disabled', reason: 'expired' }))

  assert.equal(bdds.isFeatureDisabled, false)
  assert.match(bdds.hint, /Просмотр и выгрузки работают/)
  assert.equal(billing.title, 'Тариф Pro закончился')
  assert.match(billing.text, /Реестр, выгрузки и отмена/)
})
