import test from 'node:test'
import assert from 'node:assert/strict'

import {
  isPaidFeatureId,
  paidFeatureRoute,
  resolveFinanceFeatureStates,
  resolvePaidFeatureState,
  PAID_FEATURES,
  PAID_FEATURE_BADGE,
  PAID_FEATURE_HINT,
} from '../app/utils/paidFeatures'

test('resolvePaidFeatureState: выключенная функция — замок, бейдж Pro и цена', () => {
  const state = resolvePaidFeatureState('bdds', false)

  assert.equal(state.enabled, false)
  assert.equal(state.locked, true)
  assert.equal(state.badge, PAID_FEATURE_BADGE)
  assert.equal(state.hint, PAID_FEATURE_HINT)
  assert.equal(state.badge, 'Pro')
  assert.match(state.hint || '', /тариф Pro/)
  assert.equal(state.to, '/finance/bdds')
})

test('resolvePaidFeatureState: включённая функция не носит ни замка, ни бейджа', () => {
  const state = resolvePaidFeatureState('billing', true)

  assert.equal(state.locked, false)
  assert.equal(state.badge, null)
  assert.equal(state.hint, null)
})

test('resolvePaidFeatureState: у каждой функции есть польза и перечень возможностей', () => {
  for (const id of Object.keys(PAID_FEATURES) as Array<keyof typeof PAID_FEATURES>) {
    const { feature } = resolvePaidFeatureState(id, false)

    assert.ok(feature.label.length > 0, `${id}: нет названия`)
    assert.ok(feature.benefit.length > 20, `${id}: польза описана слишком коротко`)
    assert.ok(feature.details.length >= 2, `${id}: меньше двух пунктов о том, что функция делает`)
  }
})

test('paidFeatureRoute: маршрут совпадает с идентификатором функции', () => {
  assert.equal(paidFeatureRoute('bdds'), '/finance/bdds')
  assert.equal(paidFeatureRoute('billing'), '/finance/billing')
})

test('isPaidFeatureId: чужой параметр маршрута отбрасывается', () => {
  assert.equal(isPaidFeatureId('bdds'), true)
  assert.equal(isPaidFeatureId('billing'), true)
  assert.equal(isPaidFeatureId('toString'), false)
  assert.equal(isPaidFeatureId('unknown'), false)
  assert.equal(isPaidFeatureId(42), false)
  assert.equal(isPaidFeatureId(undefined), false)
})

test('resolveFinanceFeatureStates: порядок пунктов меню — БДДС, затем счёт и акт', () => {
  const states = resolveFinanceFeatureStates({ bddsEnabled: false, billingEnabled: true })

  assert.deepEqual(states.map(state => state.feature.id), ['bdds', 'billing'])
  assert.deepEqual(states.map(state => state.locked), [true, false])
})
