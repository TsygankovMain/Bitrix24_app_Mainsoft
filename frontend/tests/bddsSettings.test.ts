import test from 'node:test'
import assert from 'node:assert/strict'

import {
  BDDS_NOTIFICATIONS_ENABLED_KEY,
  BDDS_NOTIFY_USER_IDS_KEY,
  BDDS_OVERRUN_THRESHOLD_KEY,
  BDDS_RISK_THRESHOLD_KEY,
  applyBddsSettings,
  bddsSettingsChanged,
  defaultBddsSettings,
  describeBddsThresholds,
  normalizeBddsUserIds,
  readBddsSettings,
} from '../app/utils/bddsSettings'

test('ключи совпадают с теми, что читает сервер (main/bdds_settings.py)', () => {
  assert.equal(BDDS_NOTIFICATIONS_ENABLED_KEY, 'bdds_notifications_enabled')
  assert.equal(BDDS_RISK_THRESHOLD_KEY, 'bdds_risk_threshold_percent')
  assert.equal(BDDS_OVERRUN_THRESHOLD_KEY, 'bdds_overrun_threshold_percent')
  assert.equal(BDDS_NOTIFY_USER_IDS_KEY, 'bdds_notify_user_ids')
})

test('пустая конфигурация: уведомления включены, пороги 80 и 100', () => {
  const settings = readBddsSettings({})

  assert.deepEqual(settings, defaultBddsSettings())
  assert.equal(settings.notificationsEnabled, true)
  assert.equal(settings.riskPercent, 80)
  assert.equal(settings.overrunPercent, 100)
})

test('строка «false» из app.option — это ложь, а не истина', () => {
  assert.equal(readBddsSettings({ bdds_notifications_enabled: 'false' }).notificationsEnabled, false)
  assert.equal(readBddsSettings({ bdds_notifications_enabled: '0' }).notificationsEnabled, false)
  assert.equal(readBddsSettings({ bdds_notifications_enabled: 'off' }).notificationsEnabled, false)
  assert.equal(readBddsSettings({ bdds_notifications_enabled: '1' }).notificationsEnabled, true)
  assert.equal(readBddsSettings({ bdds_notifications_enabled: true }).notificationsEnabled, true)
})

test('непонятное значение выключателя не меняет состояние по умолчанию', () => {
  assert.equal(readBddsSettings({ bdds_notifications_enabled: 'ага' }).notificationsEnabled, true)
})

test('мусор и ноль в пороге не становятся порогом', () => {
  const settings = readBddsSettings({
    bdds_risk_threshold_percent: 'восемьдесят',
    bdds_overrun_threshold_percent: 0,
  })

  assert.equal(settings.riskPercent, 80)
  assert.equal(settings.overrunPercent, 100)
})

test('запятая в пороге читается как дробь — так его наберут руками', () => {
  assert.equal(readBddsSettings({ bdds_risk_threshold_percent: '82,5' }).riskPercent, 82.5)
})

test('перепутанные местами пороги чинятся, а не ломают зону «Риск»', () => {
  const settings = readBddsSettings({
    bdds_risk_threshold_percent: 120,
    bdds_overrun_threshold_percent: 100,
  })

  assert.equal(settings.riskPercent, 100)
  assert.equal(settings.overrunPercent, 120)
})

test('список адресатов: строками, без пустых, «None» и дублей', () => {
  assert.deepEqual(normalizeBddsUserIds(['11', 12, '', null, '11', 'None', ' 13 ']), ['11', '12', '13'])
  assert.deepEqual(normalizeBddsUserIds('11'), [])
  assert.deepEqual(normalizeBddsUserIds(null), [])
})

test('сохранение кладёт свои ключи и НЕ теряет остальную конфигурацию', () => {
  const config = {
    project_sp_entity_type_id: 1036,
    project_fields_mapping: { stage_id: 'ufCrmStage' },
    billing_accountants: ['11'],
  }

  const next = applyBddsSettings(config, {
    notificationsEnabled: false,
    riskPercent: 75,
    overrunPercent: 110,
    notifyUserIds: ['11', '11', ''],
  })

  assert.equal(next.project_sp_entity_type_id, 1036)
  assert.deepEqual(next.project_fields_mapping, { stage_id: 'ufCrmStage' })
  assert.deepEqual(next.billing_accountants, ['11'])
  assert.equal(next[BDDS_NOTIFICATIONS_ENABLED_KEY], false)
  assert.equal(next[BDDS_RISK_THRESHOLD_KEY], 75)
  assert.equal(next[BDDS_OVERRUN_THRESHOLD_KEY], 110)
  assert.deepEqual(next[BDDS_NOTIFY_USER_IDS_KEY], ['11'])
})

test('сохранение тоже выправляет перепутанные пороги', () => {
  const next = applyBddsSettings({}, {
    notificationsEnabled: true,
    riskPercent: 130,
    overrunPercent: 100,
    notifyUserIds: [],
  })

  assert.equal(next[BDDS_RISK_THRESHOLD_KEY], 100)
  assert.equal(next[BDDS_OVERRUN_THRESHOLD_KEY], 130)
})

test('сохранение прочитанного обратно даёт то же самое (обход через сервер идемпотентен)', () => {
  const saved = applyBddsSettings({}, {
    notificationsEnabled: false,
    riskPercent: 70,
    overrunPercent: 90,
    notifyUserIds: ['11', '12'],
  })

  assert.deepEqual(readBddsSettings(saved), {
    notificationsEnabled: false,
    riskPercent: 70,
    overrunPercent: 90,
    notifyUserIds: ['11', '12'],
  })
})

test('кнопка «Сохранить» не горит без изменений', () => {
  const left = defaultBddsSettings()

  assert.equal(bddsSettingsChanged(left, defaultBddsSettings()), false)
  assert.equal(bddsSettingsChanged(left, { ...left, riskPercent: 70 }), true)
  assert.equal(bddsSettingsChanged(left, { ...left, notificationsEnabled: false }), true)
  assert.equal(bddsSettingsChanged(left, { ...left, notifyUserIds: ['11'] }), true)
  // Порядок в списке значим только как порядок — дубли и пустые не считаются
  // изменением, иначе кнопка горела бы после любого клика по списку.
  assert.equal(bddsSettingsChanged(
    { ...left, notifyUserIds: ['11', '12'] },
    { ...left, notifyUserIds: ['11', '12', '', '11'] }
  ), false)
})

test('подсказка под полями объясняет, что пороги решают и статус, и уведомление', () => {
  const text = describeBddsThresholds({
    notificationsEnabled: true,
    riskPercent: 75,
    overrunPercent: 105,
    notifyUserIds: [],
  })

  assert.match(text, /75%/)
  assert.match(text, /105%/)
  assert.match(text, /уведомление/)
})
