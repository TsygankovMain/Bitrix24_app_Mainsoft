import test from 'node:test'
import assert from 'node:assert/strict'

import {
  BILLING_ACCOUNTANT_IDS_KEY,
  BILLING_ALLOW_OPEN_PERIOD_KEY,
  BILLING_OUR_COMPANY_ID_KEY,
  BILLING_OUR_COMPANY_NAME_KEY,
  applyBillingSettings,
  billingSettingsChanged,
  readBillingSettings,
  type BillingSettings,
} from '../app/utils/billingSettings'

/** Заготовка настроек: тесты задают только то, что проверяют. */
function settings(patch: Partial<BillingSettings> = {}): BillingSettings {
  return {
    allowOpenPeriod: false,
    accountantIds: [],
    ourCompanyId: '',
    ourCompanyName: '',
    ...patch,
  }
}

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

  const next = applyBillingSettings(config, settings({ allowOpenPeriod: true, accountantIds: ['11'] }))

  assert.equal(next.sp_entity_type_id, 180)
  assert.deepEqual(next.fields_mapping, { hours: 'UF_CRM_1' })
  assert.equal(next[BILLING_ALLOW_OPEN_PERIOD_KEY], true)
  assert.deepEqual(next[BILLING_ACCOUNTANT_IDS_KEY], ['11'])
})

test('applyBillingSettings: возвращает копию, исходная конфигурация не меняется', () => {
  const config = { sp_entity_type_id: 180 }
  const next = applyBillingSettings(config, settings({ allowOpenPeriod: true }))

  assert.equal(BILLING_ALLOW_OPEN_PERIOD_KEY in config, false)
  assert.notEqual(next, config)
})

test('billingSettingsChanged: порядок сотрудников в списке не считается изменением', () => {
  const left = settings({ accountantIds: ['11', '12'] })
  const right = settings({ accountantIds: ['12', '11'] })

  assert.equal(billingSettingsChanged(left, right), false)
})

test('billingSettingsChanged: тумблер и состав списка изменение видят', () => {
  const base = settings({ accountantIds: ['11'] })

  assert.equal(billingSettingsChanged(base, { ...base, allowOpenPeriod: true }), true)
  assert.equal(billingSettingsChanged(base, { ...base, accountantIds: ['11', '12'] }), true)
  assert.equal(billingSettingsChanged(base, { ...base, accountantIds: ['12'] }), true)
  assert.equal(billingSettingsChanged(base, { ...base }), false)
})

test('readBillingSettings: пустая конфигурация — юрлицо из карточки проекта', () => {
  const value = readBillingSettings({})

  assert.equal(value.ourCompanyId, '')
  assert.equal(value.ourCompanyName, '')
})

test('readBillingSettings: наше юрлицо читается вместе с названием', () => {
  const value = readBillingSettings({
    [BILLING_OUR_COMPANY_ID_KEY]: 68,
    [BILLING_OUR_COMPANY_NAME_KEY]: '  Мейнсофт  ',
  })

  assert.equal(value.ourCompanyId, '68')
  assert.equal(value.ourCompanyName, 'Мейнсофт')
})

test('readBillingSettings: name без id не делает настройку заданной', () => {
  const value = readBillingSettings({ [BILLING_OUR_COMPANY_NAME_KEY]: 'Мейнсофт' })

  assert.equal(value.ourCompanyId, '')
  assert.equal(value.ourCompanyName, '')
})

test('readBillingSettings: строковые null/None не считаются идентификатором', () => {
  for (const raw of [null, undefined, 'None', 'null', 'undefined', '   ']) {
    assert.equal(readBillingSettings({ [BILLING_OUR_COMPANY_ID_KEY]: raw }).ourCompanyId, '')
  }
})

test('applyBillingSettings: наше юрлицо пишется парой ключей', () => {
  const next = applyBillingSettings({ sp_entity_type_id: 180 }, settings({
    ourCompanyId: ' 68 ',
    ourCompanyName: ' Мейнсофт ',
  }))

  assert.equal(next[BILLING_OUR_COMPANY_ID_KEY], '68')
  assert.equal(next[BILLING_OUR_COMPANY_NAME_KEY], 'Мейнсофт')
  assert.equal(next.sp_entity_type_id, 180)
})

test('applyBillingSettings: снятое юрлицо стирает и название', () => {
  const next = applyBillingSettings(
    { [BILLING_OUR_COMPANY_ID_KEY]: '68', [BILLING_OUR_COMPANY_NAME_KEY]: 'Мейнсофт' },
    settings({ ourCompanyName: 'Мейнсофт' })
  )

  assert.equal(next[BILLING_OUR_COMPANY_ID_KEY], '')
  assert.equal(next[BILLING_OUR_COMPANY_NAME_KEY], '')
})

test('billingSettingsChanged: смена юрлица — изменение', () => {
  const base = settings({ ourCompanyId: '68', ourCompanyName: 'Мейнсофт' })

  assert.equal(billingSettingsChanged(base, settings({ ourCompanyId: '7' })), true)
  assert.equal(billingSettingsChanged(base, settings()), true)
})

test('billingSettingsChanged: новое название при том же id — не изменение', () => {
  const base = settings({ ourCompanyId: '68', ourCompanyName: 'Мейнсофт' })
  const renamed = settings({ ourCompanyId: '68', ourCompanyName: 'ООО «Мейнсофт»' })

  assert.equal(billingSettingsChanged(base, renamed), false)
})
