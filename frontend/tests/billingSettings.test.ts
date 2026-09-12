import test from 'node:test'
import assert from 'node:assert/strict'

import {
  BILLING_ACCOUNTANT_IDS_KEY,
  BILLING_ALLOW_OPEN_PERIOD_KEY,
  BILLING_LINE_TASK_LEVEL_KEY,
  BILLING_LINE_TEMPLATE_KEY,
  BILLING_OUR_COMPANY_ID_KEY,
  BILLING_OUR_COMPANY_NAME_KEY,
  BILLING_ACT_TEMPLATE_ID_KEY,
  BILLING_INVOICE_TEMPLATE_ID_KEY,
  applyBillingSettings,
  billingSettingsChanged,
  readBillingSettings,
  readTemplateId,
  type BillingSettings,
} from '../app/utils/billingSettings'
import { DEFAULT_BILLING_LINE_TEMPLATE } from '../app/utils/billingLineTemplate'

/** Заготовка настроек: тесты задают только то, что проверяют. */
function settings(patch: Partial<BillingSettings> = {}): BillingSettings {
  return {
    allowOpenPeriod: false,
    accountantIds: [],
    ourCompanyId: '',
    ourCompanyName: '',
    lineTemplate: DEFAULT_BILLING_LINE_TEMPLATE,
    taskLevel: 'task',
    actTemplateId: '',
    invoiceTemplateId: '',
    ...patch,
  }
}

test('readBillingSettings: пустая конфигурация — самое строгое состояние', () => {
  const settings = readBillingSettings({})

  assert.equal(settings.allowOpenPeriod, false)
  assert.deepEqual(settings.accountantIds, [])
  assert.deepEqual(readBillingSettings(null).accountantIds, [])
})

test('readBillingSettings: формулировка строки и уровень задачи имеют значения по умолчанию', () => {
  // Пустой шаблон оставил бы каждую строку счёта без наименования работ,
  // поэтому «не задано» читается как «как по умолчанию».
  const empty = readBillingSettings({})

  assert.equal(empty.lineTemplate, DEFAULT_BILLING_LINE_TEMPLATE)
  assert.equal(empty.taskLevel, 'task')

  const configured = readBillingSettings({
    [BILLING_LINE_TEMPLATE_KEY]: '{задача} за {период}',
    [BILLING_LINE_TASK_LEVEL_KEY]: 'root',
  })

  assert.equal(configured.lineTemplate, '{задача} за {период}')
  assert.equal(configured.taskLevel, 'root')

  // Чужой уровень не имеет права укрупнить строки счёта.
  assert.equal(readBillingSettings({ [BILLING_LINE_TASK_LEVEL_KEY]: 'что-то' }).taskLevel, 'task')
})

test('applyBillingSettings: формулировка и уровень уходят на сервер нормализованными', () => {
  const next = applyBillingSettings({}, settings({ lineTemplate: '   ', taskLevel: 'root' }))

  assert.equal(next[BILLING_LINE_TEMPLATE_KEY], DEFAULT_BILLING_LINE_TEMPLATE)
  assert.equal(next[BILLING_LINE_TASK_LEVEL_KEY], 'root')
})

test('billingSettingsChanged: видит правку шаблона и уровня, но не лишний пробел', () => {
  const base = settings()

  assert.equal(billingSettingsChanged(base, settings({ lineTemplate: '{задача}' })), true)
  assert.equal(billingSettingsChanged(base, settings({ taskLevel: 'root' })), true)
  assert.equal(billingSettingsChanged(base, settings({ lineTemplate: '' })), false)
  assert.equal(
    billingSettingsChanged(base, settings({ lineTemplate: `  ${DEFAULT_BILLING_LINE_TEMPLATE}  ` })),
    false
  )
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

// ---------------------------------------------------------------------------
// Шаблоны генератора документов
// ---------------------------------------------------------------------------

test('readTemplateId: ноль, мусор и отрицательные — это «шаблон не выбран»', () => {
  // Сохранённый id 0 иначе выглядел бы как выбранный шаблон, а строка 'None'
  // (str(None) на сервере) — как настоящий идентификатор.
  assert.equal(readTemplateId(0), '')
  assert.equal(readTemplateId('0'), '')
  assert.equal(readTemplateId(''), '')
  assert.equal(readTemplateId(null), '')
  assert.equal(readTemplateId('None'), '')
  assert.equal(readTemplateId('-4'), '')
  assert.equal(readTemplateId('abc'), '')
  assert.equal(readTemplateId(4.5), '')
})

test('readTemplateId: строка из select и число с сервера — одно значение', () => {
  assert.equal(readTemplateId('4'), '4')
  assert.equal(readTemplateId(4), '4')
  assert.equal(readTemplateId(' 4 '), '4')
})

test('readBillingSettings: шаблоны читаются из конфигурации', () => {
  const parsed = readBillingSettings({
    [BILLING_ACT_TEMPLATE_ID_KEY]: 2,
    [BILLING_INVOICE_TEMPLATE_ID_KEY]: '4',
  })

  assert.equal(parsed.actTemplateId, '2')
  assert.equal(parsed.invoiceTemplateId, '4')
})

test('readBillingSettings: без шаблонов — пусто, а не ноль строкой', () => {
  const parsed = readBillingSettings({})

  assert.equal(parsed.actTemplateId, '')
  assert.equal(parsed.invoiceTemplateId, '')
})

test('applyBillingSettings: шаблоны сохраняются числами', () => {
  // Сервер хранит их int; строка из <select> дала бы вторую форму того же
  // значения, и живая проверка шаблона на портале срабатывала бы на каждом
  // сохранении любых настроек.
  const config = applyBillingSettings({}, settings({
    actTemplateId: '2',
    invoiceTemplateId: '4',
  }))

  assert.equal(config[BILLING_ACT_TEMPLATE_ID_KEY], 2)
  assert.equal(config[BILLING_INVOICE_TEMPLATE_ID_KEY], 4)
})

test('applyBillingSettings: снятый шаблон уходит нулём', () => {
  const config = applyBillingSettings({}, settings())

  assert.equal(config[BILLING_ACT_TEMPLATE_ID_KEY], 0)
  assert.equal(config[BILLING_INVOICE_TEMPLATE_ID_KEY], 0)
})

test('billingSettingsChanged: смена шаблона зажигает «Сохранить»', () => {
  assert.equal(
    billingSettingsChanged(settings({ actTemplateId: '2' }), settings()),
    true
  )
  assert.equal(
    billingSettingsChanged(
      settings({ invoiceTemplateId: '4' }),
      settings({ invoiceTemplateId: '2' })
    ),
    true
  )
})

test('billingSettingsChanged: одинаковые шаблоны в разных формах не зажигают кнопку', () => {
  // Конфигурация приходит с сервера числом, а <select> кладёт строку —
  // кнопка «Сохранить» не должна гореть сразу после загрузки страницы.
  assert.equal(
    billingSettingsChanged(
      settings({ actTemplateId: '2' }),
      settings({ actTemplateId: 2 as unknown as string })
    ),
    false
  )
  assert.equal(
    billingSettingsChanged(
      settings({ invoiceTemplateId: '' }),
      settings({ invoiceTemplateId: '0' })
    ),
    false
  )
})
