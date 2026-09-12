import test from 'node:test'
import assert from 'node:assert/strict'

import {
  OUR_COMPANY_FROM_PROJECT_CARD,
  OUR_COMPANY_FROM_SETTINGS,
  describeBillingOurCompany,
  describeOurCompanySetting,
  normalizeOurCompanySource,
} from '../app/utils/billingOurCompany'

test('normalizeOurCompanySource: чужое значение — «источник неизвестен»', () => {
  assert.equal(normalizeOurCompanySource('settings'), OUR_COMPANY_FROM_SETTINGS)
  assert.equal(normalizeOurCompanySource('project_card'), OUR_COMPANY_FROM_PROJECT_CARD)
  assert.equal(normalizeOurCompanySource(''), '')
  assert.equal(normalizeOurCompanySource(null), '')
  assert.equal(normalizeOurCompanySource('portal'), '')
})

test('describeBillingOurCompany: юрлицо из настроек названо источником', () => {
  const view = describeBillingOurCompany({
    ourCompanyId: '68',
    ourCompanyName: 'Мейнсофт',
    source: 'settings',
    cardCompanies: [{ id: '2568', name: '' }],
  })

  assert.equal(view.present, true)
  assert.equal(view.label, 'Мейнсофт')
  assert.equal(view.named, true)
  assert.equal(view.sourceText, 'из настроек приложения')
  assert.equal(view.overridden, true)
  assert.deepEqual(view.cardLabels, ['2568'])
  assert.match(view.hint, /перекрывает/)
})

test('describeBillingOurCompany: юрлицо из карточки не помечается подменой', () => {
  const view = describeBillingOurCompany({
    ourCompanyId: '7',
    ourCompanyName: 'ООО Майнсофт',
    source: 'project_card',
    cardCompanies: [{ id: '7', name: 'ООО Майнсофт' }],
  })

  assert.equal(view.sourceText, 'из карточки проекта')
  assert.equal(view.overridden, false)
  // Своё юрлицо не попадает в список «других»: расхождения нет.
  assert.deepEqual(view.cardLabels, [])
  assert.match(view.hint, /задайте его в настройках приложения/)
})

test('describeBillingOurCompany: несколько юрлиц карточек названы в пояснении', () => {
  const view = describeBillingOurCompany({
    ourCompanyId: '7',
    ourCompanyName: 'ООО Майнсофт',
    source: 'project_card',
    cardCompanies: [
      { id: '7', name: 'ООО Майнсофт' },
      { id: '2568', name: '' },
      { id: '2632', name: 'ООО Третье' },
    ],
  })

  assert.deepEqual(view.cardLabels, ['2568', 'ООО Третье'])
  assert.match(view.hint, /«2568», «ООО Третье»/)
})

test('describeBillingOurCompany: настройка без расхождения с карточками', () => {
  const view = describeBillingOurCompany({
    ourCompanyId: '68',
    ourCompanyName: 'Мейнсофт',
    source: 'settings',
    cardCompanies: [{ id: '68', name: 'Мейнсофт' }],
  })

  assert.equal(view.overridden, true)
  assert.deepEqual(view.cardLabels, [])
  assert.match(view.hint, /не зависит от того, что записано в карточках/)
})

test('describeBillingOurCompany: без названия подпись деградирует до id', () => {
  const view = describeBillingOurCompany({
    ourCompanyId: '68',
    ourCompanyName: '',
    source: 'settings',
  })

  assert.equal(view.label, '68')
  assert.equal(view.named, false)
})

test('describeBillingOurCompany: название, равное id, за название не считается', () => {
  const view = describeBillingOurCompany({
    ourCompanyId: '2568',
    ourCompanyName: '2568',
    source: 'project_card',
  })

  assert.equal(view.named, false)
  assert.equal(view.label, '2568')
})

test('describeBillingOurCompany: юрлица нет — источника тоже нет', () => {
  const view = describeBillingOurCompany({
    ourCompanyId: '',
    ourCompanyName: '',
    source: 'project_card',
  })

  assert.equal(view.present, false)
  assert.equal(view.sourceText, '')
  assert.equal(view.overridden, false)
  assert.match(view.hint, /Счёт уйдёт без наших реквизитов/)
})

test('describeOurCompanySetting: настройка не задана — прежнее поведение', () => {
  const view = describeOurCompanySetting({ ourCompanyId: '', myCompanies: [] })

  assert.equal(view.configured, false)
  assert.equal(view.missing, false)
  assert.match(view.text, /записано в карточке проекта/)
})

test('describeOurCompanySetting: название берётся из справочника портала', () => {
  const view = describeOurCompanySetting({
    ourCompanyId: '68',
    ourCompanyName: 'Старое название',
    myCompanies: [{ id: '68', name: 'Мейнсофт' }],
  })

  assert.equal(view.configured, true)
  assert.equal(view.missing, false)
  assert.equal(view.label, 'Мейнсофт')
  assert.match(view.text, /от «Мейнсофт»/)
})

test('describeOurCompanySetting: юрлица нет в списке портала — предупреждение', () => {
  const view = describeOurCompanySetting({
    ourCompanyId: '2568',
    ourCompanyName: 'Не наше',
    myCompanies: [{ id: '68', name: 'Мейнсофт' }],
  })

  assert.equal(view.missing, true)
  assert.equal(view.label, 'Не наше')
  assert.match(view.text, /не найдено среди своих компаний портала/)
})

test('describeOurCompanySetting: незагруженный справочник не обвиняет настройку', () => {
  for (const myCompanies of [null, undefined, []]) {
    const view = describeOurCompanySetting({
      ourCompanyId: '68',
      ourCompanyName: 'Мейнсофт',
      myCompanies,
    })

    assert.equal(view.missing, false)
    assert.equal(view.label, 'Мейнсофт')
  }
})
