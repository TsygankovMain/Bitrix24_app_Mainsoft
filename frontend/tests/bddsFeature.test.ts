import test from 'node:test'
import assert from 'node:assert/strict'

import { BDDS_FEATURE_CODE, resolveBddsAccess } from '../app/utils/bddsFeature'
import { parsePortalFeatures } from '../app/utils/featureAccess'
import { PAID_FEATURE_BADGE, PAID_FEATURE_HINT } from '../app/utils/paidFeatures'

test('код функции совпадает с контрактом /api/features и моделью PortalFeature', () => {
  assert.equal(BDDS_FEATURE_CODE, 'bdds')
})

test('подписка включена на сервере и флаг поднят — экран открыт, бейджа нет', () => {
  const access = resolveBddsAccess({
    features: parsePortalFeatures({ bdds: { state: 'on' } }),
    flagEnabled: true,
  })

  assert.equal(access.state, 'on')
  assert.equal(access.enabled, true)
  assert.equal(access.locked, false)
  assert.equal(access.badge, null)
  assert.equal(access.hint, null)
  assert.equal(access.unknown, false)
})

test('подписка выключена — замок, бейдж «по подписке» и подсказка «к администратору»', () => {
  const access = resolveBddsAccess({
    features: parsePortalFeatures({ bdds: { state: 'off' } }),
    flagEnabled: true,
  })

  assert.equal(access.enabled, false)
  assert.equal(access.locked, true)
  assert.equal(access.badge, PAID_FEATURE_BADGE)
  assert.equal(access.hint, PAID_FEATURE_HINT)
})

test('аварийный выключатель может ЗАКРЫТЬ включённую сервером функцию', () => {
  const access = resolveBddsAccess({
    features: parsePortalFeatures({ bdds: { state: 'on' } }),
    flagEnabled: false,
  })

  assert.equal(access.enabled, false)
  assert.equal(access.locked, true)
})

test('аварийный выключатель НЕ может открыть функцию вопреки серверу', () => {
  const access = resolveBddsAccess({
    features: parsePortalFeatures({ bdds: { state: 'off' } }),
    flagEnabled: true,
  })

  assert.equal(access.enabled, false)
})

test('ответ сервера ещё не пришёл — закрыто, но помечено unknown (экран ждёт, а не врёт)', () => {
  const access = resolveBddsAccess({ features: null, flagEnabled: true })

  assert.equal(access.unknown, true)
  assert.equal(access.enabled, false)
  assert.equal(access.locked, true)
})

test('функции нет в ответе — это «выключено», а не «включено по умолчанию»', () => {
  const access = resolveBddsAccess({
    features: parsePortalFeatures({ billing: { state: 'on' } }),
    flagEnabled: true,
  })

  assert.equal(access.state, 'off')
  assert.equal(access.enabled, false)
})

test('пробный период открывает экран и подписывает остаток дней', () => {
  const access = resolveBddsAccess({
    features: parsePortalFeatures({ bdds: { state: 'trial', trial_until: '2026-09-15' } }),
    flagEnabled: true,
    now: new Date(2026, 8, 12),
  })

  assert.equal(access.enabled, true)
  assert.equal(access.trialDaysLeft, 3)
  assert.equal(access.badge, 'пробный, осталось 3 дня')
})

test('истёкший пробный период экран НЕ закрывает: решает сервер, интерфейс только пишет правду', () => {
  const access = resolveBddsAccess({
    features: parsePortalFeatures({ bdds: { state: 'trial', trial_until: '2026-09-01' } }),
    flagEnabled: true,
    now: new Date(2026, 8, 12),
  })

  assert.equal(access.enabled, true)
  assert.equal(access.badge, 'пробный период истёк')
})

test('мусор в state читается как «выключено»', () => {
  const access = resolveBddsAccess({
    features: parsePortalFeatures({ bdds: { state: 'enabled' } }),
    flagEnabled: true,
  })

  assert.equal(access.state, 'off')
  assert.equal(access.enabled, false)
})
