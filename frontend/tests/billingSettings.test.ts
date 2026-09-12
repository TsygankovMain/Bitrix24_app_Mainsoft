import test from 'node:test'
import assert from 'node:assert/strict'

import {
  BILLING_ACCOUNTANT_IDS_KEY,
  BILLING_ALLOW_OPEN_PERIOD_KEY,
  applyBillingSettings,
  billingSettingsChanged,
  readBillingSettings,
} from '../app/utils/billingSettings'

test('readBillingSettings: пустая конфигурация — самое строгое состояние', () => {
  const settings = readBillingSettings({})

  assert.equal(settings.allowOpenPeriod, false)
  assert.deepEqual(settings.accountantIds, [])
  assert.deepEqual(readBillingSettings(null).accountantIds, [])
})

test('readBillingSettings: булево значение приходит и строкой', () => {
  assert.equal(readBillingSettings({ [BILLING_ALLOW_OPEN_PERIOD_KEY]: true }).allowOpenPeriod, true)
  assert.equal(readBillingSettings({ [BILLING_ALLOW_OPEN_PERIOD_KEY]: '1' }).allowOpenPeriod, true)
  assert.equal(readBillingSettings({ [BILLING_ALLOW_OPEN_PERIOD_KEY]: 'true' }).allowOpenPeriod, true)
  assert.equal(readBillingSettings({ [BILLING_ALLOW_OPEN_PERIOD_KEY]: '0' }).allowOpenPeriod, false)
  assert.equal(readBillingSettings({ [BILLING_ALLOW_OPEN_PERIOD_KEY]: 'нет' }).allowOpenPeriod, false)
})

test('readBillingSettings: список «Бухгалтерия» нормализуется к строкам', () => {
  const settings = readBillingSettings({ [BILLING_ACCOUNTANT_IDS_KEY]: [11, '12', '12', ''] })

  assert.deepEqual(settings.accountantIds, ['11', '12'])
})

test('applyBillingSettings: остальные ключи конфигурации не затираются', () => {
  const config = {
    sp_entity_type_id: 180,
    fields_mapping: { hours: 'UF_CRM_1' },
  }

  const next = applyBillingSettings(config, { allowOpenPeriod: true, accountantIds: ['11'] })

  assert.equal(next.sp_entity_type_id, 180)
  assert.deepEqual(next.fields_mapping, { hours: 'UF_CRM_1' })
  assert.equal(next[BILLING_ALLOW_OPEN_PERIOD_KEY], true)
  assert.deepEqual(next[BILLING_ACCOUNTANT_IDS_KEY], ['11'])
})

test('applyBillingSettings: возвращает копию, исходная конфигурация не меняется', () => {
  const config = { sp_entity_type_id: 180 }
  const next = applyBillingSettings(config, { allowOpenPeriod: true, accountantIds: [] })

  assert.equal(BILLING_ALLOW_OPEN_PERIOD_KEY in config, false)
  assert.notEqual(next, config)
})

test('billingSettingsChanged: порядок сотрудников в списке не считается изменением', () => {
  const left = { allowOpenPeriod: false, accountantIds: ['11', '12'] }
  const right = { allowOpenPeriod: false, accountantIds: ['12', '11'] }

  assert.equal(billingSettingsChanged(left, right), false)
})

test('billingSettingsChanged: тумблер и состав списка изменение видят', () => {
  const base = { allowOpenPeriod: false, accountantIds: ['11'] }

  assert.equal(billingSettingsChanged(base, { ...base, allowOpenPeriod: true }), true)
  assert.equal(billingSettingsChanged(base, { ...base, accountantIds: ['11', '12'] }), true)
  assert.equal(billingSettingsChanged(base, { ...base, accountantIds: ['12'] }), true)
  assert.equal(billingSettingsChanged(base, { ...base }), false)
})
