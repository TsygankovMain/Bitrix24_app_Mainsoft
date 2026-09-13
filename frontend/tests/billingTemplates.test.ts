import test from 'node:test'
import assert from 'node:assert/strict'

import {
  BILLING_TEMPLATE_SOURCE_HINT,
  billingTemplateOptionLabel,
  billingTemplatesEmptyText,
  describeBillingTemplateSetting,
  parseBillingTemplates,
} from '../app/utils/billingTemplates'

/**
 * Живой ответ сервера на GET /api/billing/templates — то, что он собирает из
 * ответа портала (проверено на nfr-mainsoft 12.09.2026: шаблоны приходят
 * словарём по id, флаги строками "Y"/"N", поля entityTypeId в списке нет).
 */
const SERVER_RESPONSE = {
  templates: [
    {
      id: 2,
      name: 'Акт (Россия)',
      code: 'ACT_RU',
      region: 'ru',
      active: true,
      is_default: true,
      numerator_id: 2,
      products_table_variant: 'service',
    },
    {
      id: 4,
      name: 'Счет (Россия)',
      code: 'BILL_RU',
      region: 'ru',
      active: true,
      is_default: false,
      numerator_id: 4,
      products_table_variant: '',
    },
  ],
  total: 2,
}

test('parseBillingTemplates: разбирает ответ ручки', () => {
  const templates = parseBillingTemplates(SERVER_RESPONSE)

  assert.equal(templates.length, 2)
  assert.deepEqual(templates[0], {
    id: '2',
    name: 'Акт (Россия)',
    code: 'ACT_RU',
    active: true,
    isDefault: true,
  })
  assert.equal(templates[1]?.isDefault, false)
})

test('parseBillingTemplates: принимает и готовый массив', () => {
  assert.equal(parseBillingTemplates(SERVER_RESPONSE.templates).length, 2)
})

test('parseBillingTemplates: мусор и пустой ответ — пустой список', () => {
  assert.deepEqual(parseBillingTemplates(null), [])
  assert.deepEqual(parseBillingTemplates({}), [])
  assert.deepEqual(parseBillingTemplates({ templates: 'нет' }), [])
  assert.deepEqual(parseBillingTemplates({ templates: [] }), [])
  assert.deepEqual(parseBillingTemplates([null, 'строка', 42]), [])
})

test('parseBillingTemplates: строка без id выбрасывается', () => {
  // Выбрать её нельзя, а в выпадающем списке она выглядит как рабочий вариант.
  const templates = parseBillingTemplates({
    templates: [{ name: 'Без id' }, { id: 0, name: 'Ноль' }, { id: 7, name: 'Живой' }],
  })

  assert.deepEqual(templates.map(item => item.id), ['7'])
})

test('parseBillingTemplates: дубли по id не размножаются', () => {
  const templates = parseBillingTemplates({
    templates: [{ id: 2, name: 'Акт' }, { id: '2', name: 'Акт ещё раз' }],
  })

  assert.equal(templates.length, 1)
})

test('parseBillingTemplates: флаги портала строками читаются правильно', () => {
  // Строка 'N' в JavaScript истинна: без разбора все шаблоны оказались бы
  // активными и «по умолчанию» сразу.
  const templates = parseBillingTemplates({
    templates: [{ id: 5, name: 'Старый', active: 'N', is_default: 'Y' }],
  })

  assert.equal(templates[0]?.active, false)
  assert.equal(templates[0]?.isDefault, true)
})

test('parseBillingTemplates: шаблон без названия подписывается идентификатором', () => {
  const templates = parseBillingTemplates({ templates: [{ id: 9, name: '' }] })

  assert.equal(templates[0]?.name, 'Шаблон 9')
})

test('parseBillingTemplates: отключённые шаблоны уезжают в конец списка', () => {
  const templates = parseBillingTemplates({
    templates: [
      { id: 1, name: 'Отключённый', active: false },
      { id: 2, name: 'Живой', active: true },
    ],
  })

  assert.deepEqual(templates.map(item => item.id), ['2', '1'])
})

test('billingTemplateOptionLabel: код и пометка об отключении', () => {
  assert.equal(
    billingTemplateOptionLabel({ id: '2', name: 'Акт (Россия)', code: 'ACT_RU', active: true, isDefault: true }),
    'Акт (Россия) (ACT_RU)'
  )
  assert.equal(
    billingTemplateOptionLabel({ id: '9', name: 'Свой', code: '', active: false, isDefault: false }),
    'Свой — отключён на портале'
  )
})

test('billingTemplatesEmptyText: «шаблонов нет» отправляет на портал, а не в поддержку', () => {
  const text = billingTemplatesEmptyText({})

  assert.match(text, /Битрикс24/)
  assert.match(text, /Печатные формы/)
  // Про недоступность модуля здесь речи нет: портал ответил честным нулём.
  assert.doesNotMatch(text, /не отдал/)
})

test('billingTemplatesEmptyText: отказ портала не выдаётся за отсутствие шаблонов', () => {
  const text = billingTemplatesEmptyText({ failed: true, errorText: 'Генератор документов недоступен' })

  assert.match(text, /не отдал/)
  assert.match(text, /Генератор документов недоступен/)
})

test('BILLING_TEMPLATE_SOURCE_HINT: говорит, где правится сам шаблон', () => {
  // Главное недоразумение экрана — «где поменять текст акта».
  assert.match(BILLING_TEMPLATE_SOURCE_HINT, /Битрикс24/)
  assert.match(BILLING_TEMPLATE_SOURCE_HINT, /не в приложении/)
})

test('describeBillingTemplateSetting: акт без настройки — прежнее поведение, а не поломка', () => {
  const view = describeBillingTemplateSetting({ kind: 'act', templates: [], listLoaded: true })

  assert.equal(view.configured, false)
  assert.equal(view.missing, false)
  assert.match(view.text, /по названию/)
})

test('describeBillingTemplateSetting: счёт без настройки — печать недоступна', () => {
  const view = describeBillingTemplateSetting({ kind: 'invoice', templates: [], listLoaded: true })

  assert.equal(view.configured, false)
  // Сам счёт при этом выставляется — иначе текст читался бы как «функция сломана».
  assert.match(view.text, /выставляется/)
})

test('describeBillingTemplateSetting: выбранный шаблон подписывается названием', () => {
  const view = describeBillingTemplateSetting({
    kind: 'act',
    templateId: 2,
    templates: parseBillingTemplates(SERVER_RESPONSE),
    listLoaded: true,
  })

  assert.equal(view.configured, true)
  assert.equal(view.missing, false)
  assert.match(view.label, /Акт \(Россия\)/)
  assert.match(view.text, /Номер и дата акта/)
})

test('describeBillingTemplateSetting: удалённый на портале шаблон помечается', () => {
  const view = describeBillingTemplateSetting({
    kind: 'invoice',
    templateId: 777,
    templates: parseBillingTemplates(SERVER_RESPONSE),
    listLoaded: true,
  })

  assert.equal(view.missing, true)
  assert.match(view.text, /больше нет/)
  assert.match(view.text, /Выберите другой шаблон/)
})

test('describeBillingTemplateSetting: незагруженный список не объявляет шаблон удалённым', () => {
  // Пометка «удалён» из-за недоступного генератора документов врёт про
  // настройку, которая на самом деле рабочая. Ту же осторожность соблюдает
  // сервер: он не запирает сохранение, если проверить шаблон не удалось.
  const view = describeBillingTemplateSetting({
    kind: 'act',
    templateId: 777,
    templates: [],
    listLoaded: false,
  })

  assert.equal(view.configured, true)
  assert.equal(view.missing, false)
  assert.equal(view.label, 'Шаблон 777')
})

test('describeBillingTemplateSetting: отключённый шаблон — отдельное предупреждение', () => {
  const view = describeBillingTemplateSetting({
    kind: 'act',
    templateId: 5,
    templates: parseBillingTemplates({ templates: [{ id: 5, name: 'Старый акт', active: 'N' }] }),
    listLoaded: true,
  })

  assert.equal(view.missing, false)
  assert.match(view.text, /отключён на портале/)
})
